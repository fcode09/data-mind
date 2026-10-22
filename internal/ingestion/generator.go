// Package ingestion generates only fictional records, independently of database queries.
package ingestion

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"
)

var Categories = []string{"Limpieza pública", "Alumbrado", "Vías", "Áreas verdes", "Seguridad vial"}
var Statuses = []string{"Abierto", "En proceso", "Resuelto"}

func mix(value uint64) uint64 {
	value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9
	value = (value ^ (value >> 27)) * 0x94d049bb133111eb
	return value ^ (value >> 31)
}
func Incident(id int64, seed uint64, anchor time.Time, days int, key string) []any {
	n := mix(uint64(id) + seed*1000000007)
	tenant := int(n%5) + 1
	category := Categories[(n>>5)%5]
	status := Statuses[(n>>9)%3]
	event := anchor.Add(-time.Duration((n>>14)%uint64(days*86400)+1) * time.Second)
	var resolved any
	if status == "Resuelto" {
		resolved = event.Add(time.Duration(60+(n>>25)%172740) * time.Second)
	}
	return []any{id, fmt.Sprintf("SYN-%012d", id), tenant, event, category, status, fmt.Sprintf("Sector ficticio %d", (n>>42)%20+1), resolved, fmt.Sprintf("Incidente ficticio de %s número %d. Sin datos personales reales.", category, id), key}
}

type Spec struct {
	Rows      int64     `json:"rows"`
	Seed      uint64    `json:"seed"`
	Anchor    time.Time `json:"anchor"`
	Days      int       `json:"days"`
	Offset    int64     `json:"offset"`
	BatchSize int       `json:"batch_size"`
	Key       string    `json:"batch_key"`
}

func (s Spec) Validate() error {
	if s.Rows < 1 || s.Rows > 10000000 || s.BatchSize < 1 || s.BatchSize > 100000 || s.Days < 1 || s.Days > 800 || s.Offset < 0 || s.Anchor.IsZero() {
		return fmt.Errorf("invalid bounded synthetic generation specification")
	}
	return nil
}
func (s Spec) Version() string {
	raw, _ := json.Marshal(struct {
		Rows      int64
		Seed      uint64
		Anchor    time.Time
		Days      int
		Offset    int64
		Generator string
	}{s.Rows, s.Seed, s.Anchor, s.Days, s.Offset, "go-synthetic-v1"})
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

type Manifest struct {
	Count              int64            `json:"count"`
	Tenants            map[string]int64 `json:"tenants"`
	Categories         map[string]int64 `json:"categories"`
	ResolvedCount      int64            `json:"resolved_count"`
	DurationSumSeconds int64            `json:"duration_sum_seconds"`
}

func NewManifest() Manifest {
	return Manifest{Tenants: map[string]int64{}, Categories: map[string]int64{}}
}
func (m *Manifest) Add(row []any) {
	m.Count++
	m.Tenants[fmt.Sprint(row[2])]++
	m.Categories[row[4].(string)]++
	if row[7] != nil {
		m.ResolvedCount++
		m.DurationSumSeconds += int64(row[7].(time.Time).Sub(row[3].(time.Time)).Seconds())
	}
}
