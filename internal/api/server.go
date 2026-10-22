// Package api serves the synthetic-only demo UI and verified voice proxy.
package api

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/fcode09/data-mind/internal/contracts"
	"github.com/fcode09/data-mind/internal/orchestration"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type Config struct {
	Demo                                    bool
	Secret, VoiceURL, VoiceToken, StatePath string
}
type identity struct {
	ID       string `json:"id"`
	TenantID int    `json:"tenant_id"`
	Expires  int64  `json:"expires"`
}
type savedTurn struct {
	Result  orchestration.Result `json:"result"`
	Created int64                `json:"created"`
}
type feedback struct {
	TurnID  string `json:"turn_id"`
	Rating  int    `json:"rating"`
	Note    string `json:"note"`
	Created int64  `json:"created"`
}
type state struct {
	Turns    map[string]savedTurn `json:"turns"`
	Feedback map[string]feedback  `json:"feedback"`
}
type Server struct {
	cfg      Config
	engine   orchestration.Engine
	mu       sync.Mutex
	state    state
	inflight map[string]bool
	slots    chan struct{}
}

func New(cfg Config, engine orchestration.Engine) (*Server, error) {
	if cfg.Secret == "" {
		cfg.Secret = randomID(32)
	}
	s := &Server{cfg: cfg, engine: engine, state: state{Turns: map[string]savedTurn{}, Feedback: map[string]feedback{}}, inflight: map[string]bool{}, slots: make(chan struct{}, 16)}
	if cfg.StatePath != "" {
		data, err := os.ReadFile(cfg.StatePath)
		if err == nil {
			if len(data) > 16<<20 {
				return nil, errors.New("state file too large")
			}
			if err = json.Unmarshal(data, &s.state); err != nil {
				return nil, err
			}
		} else if !os.IsNotExist(err) {
			return nil, err
		}
	}
	if s.state.Turns == nil {
		s.state.Turns = map[string]savedTurn{}
	}
	if s.state.Feedback == nil {
		s.state.Feedback = map[string]feedback{}
	}
	return s, nil
}
func randomID(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}
func write(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(value)
}
func fail(w http.ResponseWriter, status int, message string) {
	write(w, status, map[string]string{"detail": message})
}
func decode(w http.ResponseWriter, r *http.Request, value any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 16384)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if d.Decode(value) != nil {
		fail(w, 422, "Solicitud inválida")
		return false
	}
	if d.Decode(&struct{}{}) != io.EOF {
		fail(w, 422, "Solicitud inválida")
		return false
	}
	return true
}
func (s *Server) signature(body string) string {
	mac := hmac.New(sha256.New, []byte(s.cfg.Secret))
	mac.Write([]byte(body))
	return hex.EncodeToString(mac.Sum(nil))
}
func (s *Server) authenticate(r *http.Request) (identity, error) {
	var id identity
	value := r.Header.Get("Authorization")
	if !strings.HasPrefix(value, "Bearer ") {
		return id, errors.New("unauthorized")
	}
	parts := strings.Split(strings.TrimPrefix(value, "Bearer "), ".")
	if len(parts) != 2 || subtle.ConstantTimeCompare([]byte(parts[1]), []byte(s.signature(parts[0]))) != 1 {
		return id, errors.New("unauthorized")
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return id, err
	}
	err = json.Unmarshal(raw, &id)
	if err != nil || id.Expires < time.Now().Unix() || id.TenantID < 1 || id.TenantID > 5 || id.ID == "" {
		return id, errors.New("unauthorized")
	}
	return id, nil
}

const maxStateBytes = 8 << 20

// persistLocked builds a bounded candidate, writes atomically, then publishes it in memory.
// The caller holds mu and rolls back its own pending insertion when this returns an error.
func (s *Server) persistLocked(protectedKey string) error {
	candidate := state{Turns: make(map[string]savedTurn), Feedback: make(map[string]feedback)}
	cutoff := time.Now().Add(-30 * 24 * time.Hour).Unix()
	for key, turn := range s.state.Turns {
		if turn.Created >= cutoff || key == protectedKey {
			candidate.Turns[key] = turn
			if value, ok := s.state.Feedback[key]; ok {
				candidate.Feedback[key] = value
			}
		}
	}
	evict := func() bool {
		oldest := ""
		var timestamp int64 = 1<<63 - 1
		for key, turn := range candidate.Turns {
			if key != protectedKey && (turn.Created < timestamp || (turn.Created == timestamp && (oldest == "" || key < oldest))) {
				oldest = key
				timestamp = turn.Created
			}
		}
		if oldest == "" {
			return false
		}
		delete(candidate.Turns, oldest)
		delete(candidate.Feedback, oldest)
		return true
	}
	for len(candidate.Turns) > 1000 {
		if !evict() {
			return errors.New("state count limit exceeded")
		}
	}
	var payload []byte
	for {
		var err error
		payload, err = json.Marshal(candidate)
		if err != nil {
			return err
		}
		if len(payload) <= maxStateBytes {
			break
		}
		if !evict() {
			return errors.New("single turn exceeds state byte limit")
		}
	}
	if s.cfg.StatePath != "" {
		directory := filepath.Dir(s.cfg.StatePath)
		if err := os.MkdirAll(directory, 0700); err != nil {
			return err
		}
		file, err := os.CreateTemp(directory, ".data-mind-state-*")
		if err != nil {
			return err
		}
		temporary := file.Name()
		defer os.Remove(temporary)
		if _, err = file.Write(payload); err != nil {
			file.Close()
			return err
		}
		if err = file.Sync(); err != nil {
			file.Close()
			return err
		}
		if err = file.Close(); err != nil {
			return err
		}
		if err = os.Rename(temporary, s.cfg.StatePath); err != nil {
			return err
		}
	}
	s.state = candidate
	return nil
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	origin := r.Header.Get("Origin")
	if origin == "http://localhost:5173" || origin == "http://127.0.0.1:5173" {
		w.Header().Set("Access-Control-Allow-Origin", origin)
		w.Header().Set("Vary", "Origin")
		w.Header().Set("Access-Control-Allow-Headers", "Authorization,Content-Type")
		w.Header().Set("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
	}
	if r.Method == "OPTIONS" {
		w.WriteHeader(204)
		return
	}
	if r.URL.Path == "/health" && r.Method == "GET" {
		write(w, 200, map[string]string{"status": "ok", "data": "synthetic-only", "runtime": "go"})
		return
	}
	if r.URL.Path == "/api/session" && r.Method == "POST" {
		s.session(w, r)
		return
	}
	id, err := s.authenticate(r)
	if err != nil {
		fail(w, 401, "Sesión inválida o caducada")
		return
	}
	switch {
	case r.URL.Path == "/api/status" && r.Method == "GET":
		scope := contracts.Scope{TenantID: id.TenantID, FromDate: r.URL.Query().Get("from_date"), ToDateExclusive: r.URL.Query().Get("to_date_exclusive"), Timezone: "America/Lima"}
		if scope.Validate() != nil {
			fail(w, 422, "Período inválido")
			return
		}
		e, err := s.engine.Tools.Call(r.Context(), "dataset_status", scope, nil)
		if err != nil {
			fail(w, 503, "No se pudo consultar el estado")
			return
		}
		write(w, 200, e)
	case r.URL.Path == "/api/turns" && r.Method == "POST":
		s.turn(w, r, id)
	case r.URL.Path == "/api/feedback" && r.Method == "POST":
		s.feedback(w, r, id)
	case r.URL.Path == "/api/voice/speak" && r.Method == "POST":
		s.speak(w, r, id)
	case r.URL.Path == "/api/voice/transcribe" && r.Method == "POST":
		s.transcribe(w, r)
	default:
		fail(w, 404, "Ruta no encontrada")
	}
}
func (s *Server) session(w http.ResponseWriter, r *http.Request) {
	if !s.cfg.Demo {
		fail(w, 403, "El inicio de sesión de demostración está deshabilitado")
		return
	}
	var input struct {
		TenantID int `json:"tenant_id"`
	}
	if !decode(w, r, &input) {
		return
	}
	if input.TenantID < 1 || input.TenantID > 5 {
		fail(w, 422, "Organización inválida")
		return
	}
	id := identity{randomID(18), input.TenantID, time.Now().Add(8 * time.Hour).Unix()}
	raw, _ := json.Marshal(id)
	body := base64.RawURLEncoding.EncodeToString(raw)
	write(w, 200, map[string]any{"token": body + "." + s.signature(body), "tenant_id": id.TenantID, "expires": id.Expires, "demo": true})
}
func (s *Server) turn(w http.ResponseWriter, r *http.Request, id identity) {
	var input struct {
		TurnID          string `json:"turn_id"`
		Message         string `json:"message"`
		FromDate        string `json:"from_date"`
		ToDateExclusive string `json:"to_date_exclusive"`
	}
	if !decode(w, r, &input) {
		return
	}
	if len(input.TurnID) < 8 || len(input.TurnID) > 100 || len(input.Message) < 1 || len(input.Message) > 2000 {
		fail(w, 422, "Turno inválido")
		return
	}
	scope := contracts.Scope{TenantID: id.TenantID, FromDate: input.FromDate, ToDateExclusive: input.ToDateExclusive, Timezone: "America/Lima"}
	if scope.Validate() != nil {
		fail(w, 422, "Período inválido")
		return
	}
	key := id.ID + ":" + input.TurnID
	s.mu.Lock()
	if saved, ok := s.state.Turns[key]; ok {
		s.mu.Unlock()
		write(w, 200, saved.Result)
		return
	}
	if s.inflight[key] {
		s.mu.Unlock()
		fail(w, 409, "Este turno ya está en curso")
		return
	}
	select {
	case s.slots <- struct{}{}:
	default:
		s.mu.Unlock()
		fail(w, 429, "Demasiadas consultas")
		return
	}
	s.inflight[key] = true
	s.mu.Unlock()
	defer func() { s.mu.Lock(); delete(s.inflight, key); s.mu.Unlock(); <-s.slots }()
	ctx, cancel := context.WithTimeout(r.Context(), 25*time.Second)
	defer cancel()
	result, err := s.engine.Answer(ctx, input.Message, scope)
	if err != nil {
		fail(w, 503, "No pude verificar la consulta. No se generó una respuesta con datos.")
		return
	}
	result.TurnID = input.TurnID
	s.mu.Lock()
	s.state.Turns[key] = savedTurn{result, time.Now().Unix()}
	err = s.persistLocked(key)
	if err != nil {
		delete(s.state.Turns, key)
	}
	s.mu.Unlock()
	if err != nil {
		fail(w, 503, "No se pudo guardar el turno")
		return
	}
	write(w, 200, result)
}
func (s *Server) feedback(w http.ResponseWriter, r *http.Request, id identity) {
	var input feedback
	if !decode(w, r, &input) {
		return
	}
	if (input.Rating != 1 && input.Rating != -1) || len(input.Note) > 1000 {
		fail(w, 422, "Valoración inválida")
		return
	}
	key := id.ID + ":" + input.TurnID
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.state.Turns[key]; !ok {
		fail(w, 404, "Turno no encontrado")
		return
	}
	input.Created = time.Now().Unix()
	previous, existed := s.state.Feedback[key]
	s.state.Feedback[key] = input
	if s.persistLocked(key) != nil {
		if existed {
			s.state.Feedback[key] = previous
		} else {
			delete(s.state.Feedback, key)
		}
		fail(w, 503, "No se pudo guardar")
		return
	}
	write(w, 200, map[string]bool{"saved": true, "automatic_training": false})
}
func (s *Server) voiceRequest(ctx context.Context, path, contentType string, body io.Reader) (*http.Response, error) {
	if s.cfg.VoiceToken == "" {
		return nil, errors.New("voice not configured")
	}
	req, err := http.NewRequestWithContext(ctx, "POST", strings.TrimRight(s.cfg.VoiceURL, "/")+path, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+s.cfg.VoiceToken)
	req.Header.Set("Content-Type", contentType)
	return (&http.Client{Timeout: 95 * time.Second}).Do(req)
}
func (s *Server) speak(w http.ResponseWriter, r *http.Request, id identity) {
	var input struct {
		TurnID string `json:"turn_id"`
	}
	if !decode(w, r, &input) {
		return
	}
	s.mu.Lock()
	saved, ok := s.state.Turns[id.ID+":"+input.TurnID]
	s.mu.Unlock()
	if !ok {
		fail(w, 404, "Turno no encontrado")
		return
	}
	if !saved.Result.Verified || saved.Result.Evidence == nil {
		fail(w, 409, "La respuesta no tiene evidencia verificada")
		return
	}
	body, _ := json.Marshal(map[string]string{"text": saved.Result.Answer})
	response, err := s.voiceRequest(r.Context(), "/synthesize", "application/json", bytes.NewReader(body))
	if err != nil {
		fail(w, 503, "La voz local no está disponible")
		return
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		fail(w, 503, "La voz local no está disponible")
		return
	}
	w.Header().Set("Content-Type", "audio/wav")
	w.Header().Set("Cache-Control", "no-store")
	io.Copy(w, io.LimitReader(response.Body, 6<<20))
}
func (s *Server) transcribe(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 4<<20+65536)
	if err := r.ParseMultipartForm(4 << 20); err != nil {
		fail(w, 413, "Audio demasiado grande")
		return
	}
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	file, _, err := r.FormFile("file")
	if err != nil {
		fail(w, 422, "Falta audio")
		return
	}
	defer file.Close()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, _ := writer.CreateFormFile("file", "question.wav")
	n, err := io.Copy(part, io.LimitReader(file, (4<<20)+1))
	if err != nil || n > 4<<20 {
		fail(w, 413, "Audio demasiado grande")
		return
	}
	writer.Close()
	response, err := s.voiceRequest(r.Context(), "/transcribe", writer.FormDataContentType(), &body)
	if err != nil {
		fail(w, 503, "El modelo local de voz no está disponible")
		return
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		fail(w, 503, "El modelo local de voz no está disponible")
		return
	}
	var value struct {
		Text string `json:"text"`
	}
	if json.NewDecoder(io.LimitReader(response.Body, 8192)).Decode(&value) != nil {
		fail(w, 503, "Transcripción inválida")
		return
	}
	write(w, 200, value)
}
