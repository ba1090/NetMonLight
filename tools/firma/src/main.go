// Firma NetMon (Windows, macOS e Linux): firma i pacchetti netmon-<versione>.zip con la chiave di
// rilascio dell'autore. Su Windows è tools/windows/FirmaNetMon.exe; sul Mac lo avvia l'app
// tools/mac/Firma NetMon.app (al posto delle finestre di sistema di firma-netmon-classic).
//
// Un solo eseguibile, senza installazione. Al doppio clic apre nel browser una pagina servita SOLO a
// questo computer (127.0.0.1, porta casuale, codice segreto nell'indirizzo) e si chiude da sola quando
// la pagina viene chiusa. La chiave privata non lascia mai il computer: sta in
// %APPDATA%\NetMon Firma (su macOS ~/Library/Application Support/NetMon Firma, la stessa cartella
// dell'app per il Mac), cifrata con una password nello stesso formato di `openssl ec -aes256`, quindi
// le copie di riserva valgono anche nell'app per il Mac e viceversa.
//
// Crittografia identica all'app per il Mac e alla verifica sulla VM (netmon-vm-selfupdate):
// ECDSA P-256 su SHA-256 dello zip, firma DER in base64 su una riga (file .sig).
//
// Compilazione: tools/firma/build.sh (solo libreria standard di Go; l'icona di Windows con go-winres).
package main

import (
	"archive/zip"
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"crypto/x509"
	_ "embed"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"time"
)

const (
	appVersion  = "1.0"
	minPassword = 10
	maxUpload   = 20 << 20 // un pacchetto netmon è al massimo 10 MB
	keyInZip    = "netmon/server/release-key.pub"
	idleLimit   = 20 * time.Minute // pagina chiusa: nessun segnale da tanto così (le schede in secondo
	// piano mandano il segnale di rado, e i file firmati sono già nella pagina)
	openLimit = 3 * time.Minute // pagina mai aperta
)

//go:embed page.html
var pageHTML string

var (
	keyDir   string
	token    string
	origin   string
	lastSeen = time.Now()
	opened   bool
	mu       sync.Mutex
)

// ------------------------------------------------------------------ chiavi
func keyPath() string { return filepath.Join(keyDir, "release-signing.key") }
func pubPath() string { return filepath.Join(keyDir, "release-key.pub") }

func fingerprint(pub *ecdsa.PublicKey) string {
	der, err := x509.MarshalPKIXPublicKey(pub)
	if err != nil {
		return "?"
	}
	h := sha256.Sum256(der)
	s := hex.EncodeToString(h[:])[:16]
	return s[0:4] + " " + s[4:8] + " " + s[8:12] + " " + s[12:16]
}

func pubPEM(pub *ecdsa.PublicKey) []byte {
	der, _ := x509.MarshalPKIXPublicKey(pub)
	return pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der})
}

func parsePub(data []byte) (*ecdsa.PublicKey, error) {
	blk, _ := pem.Decode(data)
	if blk == nil {
		return nil, errors.New("chiave pubblica non valida")
	}
	k, err := x509.ParsePKIXPublicKey(blk.Bytes)
	if err != nil {
		return nil, errors.New("chiave pubblica non valida")
	}
	pub, ok := k.(*ecdsa.PublicKey)
	if !ok || pub.Curve != elliptic.P256() {
		return nil, errors.New("la chiave pubblica non è una chiave P-256")
	}
	return pub, nil
}

func loadPub() (*ecdsa.PublicKey, []byte, error) {
	data, err := os.ReadFile(pubPath())
	if err != nil {
		return nil, nil, err
	}
	pub, err := parsePub(data)
	return pub, data, err
}

// decryptKey: chiave privata cifrata come `openssl ec -aes256` (BEGIN EC PRIVATE KEY con DEK-Info).
func decryptKey(data []byte, password string) (*ecdsa.PrivateKey, error) {
	blk, _ := pem.Decode(data)
	if blk == nil {
		return nil, errors.New("non è un file di chiave di NetMon")
	}
	if blk.Type == "ENCRYPTED PRIVATE KEY" {
		return nil, errors.New("formato di chiave non supportato (PKCS#8): usa la copia di riserva fatta da «Firma NetMon»")
	}
	der := blk.Bytes
	//lint:ignore SA1019 formato tradizionale di OpenSSL, lo stesso dell'app per il Mac
	if x509.IsEncryptedPEMBlock(blk) { //nolint:staticcheck
		var err error
		der, err = x509.DecryptPEMBlock(blk, []byte(password)) //nolint:staticcheck
		if err != nil {
			return nil, errors.New("password della chiave non corretta")
		}
	}
	priv, err := x509.ParseECPrivateKey(der)
	if err != nil {
		if k, err2 := x509.ParsePKCS8PrivateKey(der); err2 == nil {
			if p, ok := k.(*ecdsa.PrivateKey); ok {
				priv, err = p, nil
			}
		}
	}
	if err != nil {
		return nil, errors.New("password della chiave non corretta")
	}
	if priv.Curve != elliptic.P256() {
		return nil, errors.New("la chiave non è una chiave P-256")
	}
	return priv, nil
}

func loadPriv(password string) (*ecdsa.PrivateKey, error) {
	data, err := os.ReadFile(keyPath())
	if err != nil {
		return nil, errors.New("su questo computer non c'è ancora una chiave di rilascio")
	}
	priv, err := decryptKey(data, password)
	if err != nil {
		return nil, err
	}
	if pub, _, err := loadPub(); err == nil && !pub.Equal(&priv.PublicKey) {
		return nil, errors.New("la chiave privata e quella pubblica salvate non corrispondono")
	}
	return priv, nil
}

func writeFile(path string, data []byte, mode os.FileMode) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, mode); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func saveKey(encrypted []byte, pub *ecdsa.PublicKey) error {
	if err := os.MkdirAll(keyDir, 0o700); err != nil {
		return err
	}
	if err := writeFile(keyPath(), encrypted, 0o600); err != nil {
		return err
	}
	return writeFile(pubPath(), pubPEM(pub), 0o644)
}

func createKey(password string) (*ecdsa.PublicKey, error) {
	if len([]rune(password)) < minPassword {
		return nil, fmt.Errorf("la password deve avere almeno %d caratteri", minPassword)
	}
	if _, err := os.Stat(keyPath()); err == nil {
		return nil, errors.New("su questo computer c'è già una chiave di rilascio")
	}
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	der, err := x509.MarshalECPrivateKey(priv)
	if err != nil {
		return nil, err
	}
	//lint:ignore SA1019 stesso formato di `openssl ec -aes256` (compatibile con l'app per il Mac)
	blk, err := x509.EncryptPEMBlock(rand.Reader, "EC PRIVATE KEY", der, []byte(password), x509.PEMCipherAES256) //nolint:staticcheck
	if err != nil {
		return nil, err
	}
	return &priv.PublicKey, saveKey(pem.EncodeToMemory(blk), &priv.PublicKey)
}

// ------------------------------------------------------------------ pacchetti
var versionRE = regexp.MustCompile(`^\d+\.\d+\.\d{8}-\d{6}$`)

func readEntry(zr *zip.Reader, name string, limit int64) ([]byte, bool) {
	for _, f := range zr.File {
		if f.Name == name {
			rc, err := f.Open()
			if err != nil {
				return nil, false
			}
			defer rc.Close()
			b, err := io.ReadAll(io.LimitReader(rc, limit))
			return b, err == nil
		}
	}
	return nil, false
}

// withKey: lo stesso zip con in più la chiave pubblica (gli altri file copiati così come sono).
func withKey(data []byte, pub []byte) ([]byte, error) {
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for _, f := range zr.File {
		if err := zw.Copy(f); err != nil {
			return nil, err
		}
	}
	h := &zip.FileHeader{Name: keyInZip, Method: zip.Deflate, Modified: time.Now()}
	h.SetMode(0o644)
	w, err := zw.CreateHeader(h)
	if err != nil {
		return nil, err
	}
	if _, err := w.Write(pub); err != nil {
		return nil, err
	}
	if err := zw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

type signResult struct {
	OK       bool   `json:"ok"`
	Need     string `json:"need,omitempty"` // "confirm": il pacchetto contiene un'altra chiave
	Message  string `json:"message,omitempty"`
	Version  string `json:"version,omitempty"`
	FP       string `json:"fp,omitempty"`
	Other    string `json:"other,omitempty"`
	AddedKey bool   `json:"added_key,omitempty"`
	// I file firmati arrivano nella risposta: la pagina li scarica da sé, anche se il programma si è già
	// chiuso (niente indirizzi da cui scaricare, che sparirebbero con lui).
	ZipB64  string `json:"zip_b64,omitempty"` // lo zip con la chiave aggiunta, in base64
	ZipName string `json:"zip_name,omitempty"`
	SigText string `json:"sig_text,omitempty"`
	SigName string `json:"sig_name,omitempty"`
}

func signZip(data []byte, name, password string, confirmOther bool) signResult {
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return signResult{Message: "Non è un file zip valido."}
	}
	v, ok := readEntry(zr, "netmon/VERSION", 100)
	version := strings.TrimSpace(string(v))
	if !ok || !versionRE.MatchString(version) {
		return signResult{Message: "Non sembra un pacchetto netmon (manca netmon/VERSION): serve lo zip del rilascio, non il «Download ZIP» di GitHub."}
	}
	pub, pubData, err := loadPub()
	if err != nil {
		return signResult{Message: "Su questo computer non c'è ancora una chiave di rilascio."}
	}
	res := signResult{Version: version, FP: fingerprint(pub)}
	inside, has := readEntry(zr, keyInZip, 4096)
	switch {
	case !has:
		res.AddedKey = true
	default:
		other, err := parsePub(inside)
		if err != nil {
			return signResult{Message: "Il pacchetto contiene una chiave pubblica non valida (server/release-key.pub)."}
		}
		if !other.Equal(pub) && !confirmOther {
			return signResult{Need: "confirm", Version: version, FP: res.FP, Other: fingerprint(other),
				Message: "Il pacchetto contiene una chiave pubblica DIVERSA dalla tua: dopo l'installazione la VM accetterà solo pacchetti firmati con quella."}
		}
	}
	// prima la password: lo zip non si tocca se è sbagliata
	priv, err := loadPriv(password)
	if err != nil {
		return signResult{Message: strings.ToUpper(err.Error()[:1]) + err.Error()[1:] + "."}
	}
	if res.AddedKey {
		if data, err = withKey(data, pubData); err != nil {
			return signResult{Message: "Non riesco ad aggiungere la chiave al pacchetto: " + err.Error()}
		}
	}
	sum := sha256.Sum256(data)
	sig, err := ecdsa.SignASN1(rand.Reader, priv, sum[:])
	if err != nil || !ecdsa.VerifyASN1(pub, sum[:], sig) {
		return signResult{Message: "La firma appena fatta non si verifica: chiave danneggiata?"}
	}
	base := filepath.Base(strings.ReplaceAll(name, "\\", "/"))
	if !strings.HasSuffix(strings.ToLower(base), ".zip") || base == ".zip" {
		base = "netmon-" + version + ".zip"
	}
	res.OK, res.SigName = true, base+".sig"
	res.SigText = base64.StdEncoding.EncodeToString(sig) + "\n"
	if res.AddedKey {
		res.ZipName = base
		res.ZipB64 = base64.StdEncoding.EncodeToString(data)
	}
	return res
}

func verifyZip(data []byte, sigText string) (bool, string, string) {
	pub, _, err := loadPub()
	if err != nil {
		return false, "", "Su questo computer non c'è ancora una chiave di rilascio."
	}
	sig, err := base64.StdEncoding.DecodeString(strings.TrimSpace(sigText))
	if err != nil || len(sig) == 0 || len(sig) > 512 {
		return false, fingerprint(pub), "Il file .sig non è una firma di «Firma NetMon»."
	}
	sum := sha256.Sum256(data)
	version := ""
	if zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data))); err == nil {
		v, _ := readEntry(zr, "netmon/VERSION", 100)
		version = strings.TrimSpace(string(v))
	}
	if ecdsa.VerifyASN1(pub, sum[:], sig) {
		return true, fingerprint(pub), version
	}
	return false, fingerprint(pub), "Firma NON valida per la tua chiave: il pacchetto è stato modificato dopo la firma, oppure è firmato con un'altra chiave."
}

// ------------------------------------------------------------------ server locale
func jsonOut(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(v)
}

func fail(w http.ResponseWriter, msg string) { jsonOut(w, map[string]any{"ok": false, "message": msg}) }

func formFile(r *http.Request, field string) ([]byte, string, error) {
	f, h, err := r.FormFile(field)
	if err != nil {
		return nil, "", err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, maxUpload))
	return b, h.Filename, err
}

func handler(port int) http.Handler {
	host := fmt.Sprintf("127.0.0.1:%d", port)
	prefix := "/" + token + "/"
	mux := http.NewServeMux()
	mux.HandleFunc(prefix, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != prefix {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		io.WriteString(w, pageHTML)
	})
	mux.HandleFunc(prefix+"api/state", func(w http.ResponseWriter, r *http.Request) {
		out := map[string]any{"key": false, "dir": keyDir, "version": appVersion}
		if pub, data, err := loadPub(); err == nil {
			_, errKey := os.Stat(keyPath())
			out["key"], out["fp"], out["pub"] = errKey == nil, fingerprint(pub), string(data)
		}
		jsonOut(w, out)
	})
	mux.HandleFunc(prefix+"api/create", func(w http.ResponseWriter, r *http.Request) {
		var b struct{ Password, Repeat string }
		if json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&b) != nil {
			fail(w, "Richiesta non valida.")
			return
		}
		if b.Password != b.Repeat {
			fail(w, "Le due password non coincidono.")
			return
		}
		pub, err := createKey(b.Password)
		if err != nil {
			fail(w, strings.ToUpper(err.Error()[:1])+err.Error()[1:]+".")
			return
		}
		jsonOut(w, map[string]any{"ok": true, "fp": fingerprint(pub)})
	})
	mux.HandleFunc(prefix+"api/import", func(w http.ResponseWriter, r *http.Request) {
		data, _, err := formFile(r, "key")
		if err != nil || len(data) > 16384 {
			fail(w, "Scegli il file della chiave (netmon-release-signing.key).")
			return
		}
		_, errKey := os.Stat(keyPath())
		replace := r.FormValue("replace") == "1"
		if errKey == nil && !replace {
			fail(w, "Su questo computer c'è già una chiave di rilascio.")
			return
		}
		priv, err := decryptKey(data, r.FormValue("password"))
		if err != nil {
			fail(w, "Non è una chiave di rilascio di NetMon, oppure la password non è corretta.")
			return
		}
		// chiave di un altro computer al posto di quella di qui: la vecchia non si cancella, si mette da parte
		var kept string
		if errKey == nil {
			stamp := time.Now().Format("20060102-150405")
			kept = keyPath() + ".sostituita-" + stamp
			if err := os.Rename(keyPath(), kept); err != nil {
				fail(w, "Non riesco a mettere da parte la chiave attuale: "+err.Error())
				return
			}
			os.Rename(pubPath(), pubPath()+".sostituita-"+stamp)
		}
		if err := saveKey(data, &priv.PublicKey); err != nil {
			fail(w, "Salvataggio non riuscito: "+err.Error())
			return
		}
		jsonOut(w, map[string]any{"ok": true, "fp": fingerprint(&priv.PublicKey), "kept": kept})
	})
	mux.HandleFunc(prefix+"api/sign", func(w http.ResponseWriter, r *http.Request) {
		data, name, err := formFile(r, "zip")
		if err != nil {
			fail(w, "Scegli il pacchetto netmon-….zip.")
			return
		}
		jsonOut(w, signZip(data, name, r.FormValue("password"), r.FormValue("confirm") == "1"))
	})
	mux.HandleFunc(prefix+"api/verify", func(w http.ResponseWriter, r *http.Request) {
		data, _, err := formFile(r, "zip")
		sig, _, err2 := formFile(r, "sig")
		if err != nil || err2 != nil {
			fail(w, "Scegli lo zip e il suo file .sig.")
			return
		}
		ok, fp, msg := verifyZip(data, string(sig))
		jsonOut(w, map[string]any{"ok": ok, "fp": fp, "message": msg})
	})
	// copia di riserva: chiave privata (cifrata con la password) e pubblica, scaricate dalla pagina
	mux.HandleFunc(prefix+"api/backup", func(w http.ResponseWriter, r *http.Request) {
		key, err1 := os.ReadFile(keyPath())
		pub, err2 := os.ReadFile(pubPath())
		if err1 != nil || err2 != nil {
			fail(w, "Su questo computer non c'è ancora una chiave di rilascio.")
			return
		}
		jsonOut(w, map[string]any{"ok": true, "key": string(key), "pub": string(pub)})
	})
	mux.HandleFunc(prefix+"api/ping", func(w http.ResponseWriter, r *http.Request) { jsonOut(w, map[string]bool{"ok": true}) })
	mux.HandleFunc(prefix+"api/quit", func(w http.ResponseWriter, r *http.Request) {
		jsonOut(w, map[string]bool{"ok": true})
		go func() { time.Sleep(300 * time.Millisecond); os.Exit(0) }()
	})

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// solo questo computer, solo con il codice segreto, solo dalla pagina stessa (niente siti esterni)
		if r.Host != host {
			http.Error(w, "indirizzo non ammesso", http.StatusForbidden)
			return
		}
		if !strings.HasPrefix(r.URL.Path, prefix) ||
			subtle.ConstantTimeCompare([]byte(r.URL.Path[1:len(prefix)-1]), []byte(token)) != 1 {
			http.NotFound(w, r)
			return
		}
		if r.Method != http.MethodGet {
			if r.Method != http.MethodPost || r.Header.Get("Origin") != origin {
				http.Error(w, "richiesta non ammessa", http.StatusForbidden)
				return
			}
			r.Body = http.MaxBytesReader(w, r.Body, maxUpload+1<<20)
		}
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: 'self'; connect-src 'self'; media-src blob:; frame-ancestors 'none'; form-action 'none'; base-uri 'none'")
		mu.Lock()
		lastSeen, opened = time.Now(), true
		mu.Unlock()
		mux.ServeHTTP(w, r)
	})
}

func openBrowser(url string) {
	if os.Getenv("FIRMA_NETMON_NO_BROWSER") != "" {
		return
	}
	switch runtime.GOOS {
	case "windows":
		exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
	case "darwin":
		exec.Command("open", url).Start()
	default:
		exec.Command("xdg-open", url).Start()
	}
}

func main() {
	keyDir = os.Getenv("FIRMA_NETMON_DIR")
	if keyDir == "" {
		base, err := os.UserConfigDir() // Windows: %APPDATA%; macOS: ~/Library/Application Support
		if err != nil {
			base = "."
		}
		keyDir = filepath.Join(base, "NetMon Firma")
	}
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		os.Exit(1)
	}
	token = base64.RawURLEncoding.EncodeToString(b)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		fmt.Fprintln(os.Stderr, "Non riesco ad aprire la pagina locale:", err)
		os.Exit(1)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	origin = fmt.Sprintf("http://127.0.0.1:%d", port)
	url := fmt.Sprintf("%s/%s/", origin, token)
	fmt.Println("Firma NetMon:", url)
	go func() {
		for range time.Tick(5 * time.Second) {
			mu.Lock()
			idle, was := time.Since(lastSeen), opened
			mu.Unlock()
			if (was && idle > idleLimit) || (!was && idle > openLimit) {
				os.Exit(0)
			}
		}
	}()
	openBrowser(url)
	srv := &http.Server{Handler: handler(port), ReadHeaderTimeout: 10 * time.Second}
	srv.Serve(ln)
}
