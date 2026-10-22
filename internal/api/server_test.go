package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/fcode09/data-mind/internal/contracts"
	"github.com/fcode09/data-mind/internal/orchestration"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type fakeTools struct{}

func (fakeTools) Call(_ context.Context, _ string, s contracts.Scope, _ map[string]any) (contracts.Evidence, error) {
	return contracts.Evidence{QueryID: "fixture", DatasetVersion: "v", EffectiveScope: s, TotalMatching: 2, ReturnedRows: 1, Rows: []map[string]any{{"count": 2}}}, nil
}
func request(t *testing.T, s http.Handler, path, token string, body any) *httptest.ResponseRecorder {
	t.Helper()
	raw, _ := json.Marshal(body)
	r := httptest.NewRequest("POST", path, bytes.NewReader(raw))
	r.Header.Set("Content-Type", "application/json")
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	return w
}
func token(t *testing.T, s http.Handler) string {
	r := request(t, s, "/api/session", "", map[string]int{"tenant_id": 1})
	var v map[string]any
	json.Unmarshal(r.Body.Bytes(), &v)
	return v["token"].(string)
}
func TestAuthTurnsAndSpeechGate(t *testing.T) {
	s, err := New(Config{Demo: true, Secret: "test", StatePath: filepath.Join(t.TempDir(), "state.json")}, orchestration.Engine{Tools: fakeTools{}})
	if err != nil {
		t.Fatal(err)
	}
	a := token(t, s)
	b := token(t, s)
	turn := map[string]string{"turn_id": "fixture-turn-001", "message": "hola", "from_date": "2026-01-01", "to_date_exclusive": "2026-02-01"}
	if r := request(t, s, "/api/turns", a, turn); r.Code != 200 {
		t.Fatal(r.Body.String())
	}
	if r := request(t, s, "/api/voice/speak", a, map[string]string{"turn_id": "fixture-turn-001"}); r.Code != 409 {
		t.Fatal(r.Code)
	}
	if r := request(t, s, "/api/feedback", b, map[string]any{"turn_id": "fixture-turn-001", "rating": 1}); r.Code != 404 {
		t.Fatal("other session can feedback", r.Code)
	}
	turn["turn_id"] = "fixture-turn-002"
	turn["message"] = "cuántos"
	r := request(t, s, "/api/turns", a, turn)
	if r.Code != 200 {
		t.Fatal(r.Body.String())
	}
	if r = request(t, s, "/api/feedback", a, map[string]any{"turn_id": "fixture-turn-002", "rating": 1}); r.Code != 200 {
		t.Fatal(r.Body.String())
	}
}
func TestDemoOff(t *testing.T) {
	s, _ := New(Config{}, orchestration.Engine{})
	if request(t, s, "/api/session", "", map[string]int{"tenant_id": 1}).Code != 403 {
		t.Fatal("demo enabled by default")
	}
}

func TestStateByteCapAndReload(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")
	s, err := New(Config{StatePath: path}, orchestration.Engine{})
	if err != nil {
		t.Fatal(err)
	}
	for index := 0; index < 20; index++ {
		key := fmt.Sprintf("session:%03d", index)
		rows := make([]map[string]any, 800)
		for n := range rows {
			rows[n] = map[string]any{"description": strings.Repeat("x", 1000)}
		}
		s.state.Turns[key] = savedTurn{Result: orchestration.Result{TurnID: key, Evidence: &contracts.Evidence{Rows: rows}}, Created: time.Now().Unix() + int64(index)}
		if err = s.persistLocked(key); err != nil {
			t.Fatal(err)
		}
	}
	info, err := os.Stat(path)
	if err != nil || info.Size() > maxStateBytes {
		t.Fatal("serialized state exceeded bound", err)
	}
	reloaded, err := New(Config{StatePath: path}, orchestration.Engine{})
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := reloaded.state.Turns["session:019"]; !ok {
		t.Fatal("newest turn evicted")
	}
	if len(reloaded.state.Turns) >= 20 {
		t.Fatal("oversized state was not evicted")
	}
}
func TestFailedFeedbackWriteIsNotSaved(t *testing.T) {
	s, _ := New(Config{Demo: true, Secret: "test"}, orchestration.Engine{Tools: fakeTools{}})
	auth := token(t, s)
	r := httptest.NewRequest("GET", "/", nil)
	r.Header.Set("Authorization", "Bearer "+auth)
	id, _ := s.authenticate(r)
	key := id.ID + ":fixture-turn"
	s.state.Turns[key] = savedTurn{Created: time.Now().Unix()}
	directory := filepath.Join(t.TempDir(), "directory")
	os.Mkdir(directory, 0700)
	s.cfg.StatePath = directory
	result := request(t, s, "/api/feedback", auth, map[string]any{"turn_id": "fixture-turn", "rating": 1})
	if result.Code != 503 {
		t.Fatal(result.Code)
	}
	if _, ok := s.state.Feedback[key]; ok {
		t.Fatal("failed feedback remained saved in memory")
	}
}
