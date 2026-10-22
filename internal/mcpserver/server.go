// Package mcpserver exposes only bounded read tools over the official MCP transport.
package mcpserver

import (
	"context"
	"crypto/subtle"
	"errors"
	"github.com/fcode09/data-mind/internal/contracts"
	"github.com/fcode09/data-mind/internal/data"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"net/http"
	"strconv"
	"time"
)

type Repository interface {
	DatasetStatus(context.Context, contracts.Scope) (contracts.Evidence, error)
	IncidentsSummary(context.Context, contracts.Scope, string, int, data.Filters) (contracts.Evidence, error)
	IncidentsTimeseries(context.Context, contracts.Scope, data.Filters) (contracts.Evidence, error)
	IncidentsSearch(context.Context, contracts.Scope, string, int, string, data.Filters) (contracts.Evidence, error)
	IncidentDetail(context.Context, contracts.Scope, int64) (contracts.Evidence, error)
	ResolutionStatistics(context.Context, contracts.Scope, data.Filters) (contracts.Evidence, error)
	KnowledgeSearch(context.Context, contracts.Scope, string, int) (contracts.Evidence, error)
}
type tenantKey struct{}
type Input struct {
	Scope      contracts.Scope `json:"scope"`
	GroupBy    string          `json:"group_by,omitempty"`
	Limit      int             `json:"limit,omitempty"`
	Text       string          `json:"text,omitempty"`
	Query      string          `json:"query,omitempty"`
	Cursor     string          `json:"cursor,omitempty"`
	IncidentID int64           `json:"incident_id,omitempty"`
	Category   string          `json:"category,omitempty"`
	Status     string          `json:"status,omitempty"`
}

func Handler(repo Repository, token string) http.Handler {
	server := mcp.NewServer(&mcp.Implementation{Name: "data-mind", Version: "2.0.0"}, nil)
	names := []string{"dataset_status", "incidents_summary", "incidents_timeseries", "incidents_search", "incident_detail", "resolution_statistics", "knowledge_search"}
	for _, name := range names {
		mcp.AddTool(server, &mcp.Tool{Name: name, Description: "Read bounded synthetic data within authenticated tenant and half-open date scope."}, func(ctx context.Context, req *mcp.CallToolRequest, input Input) (*mcp.CallToolResult, contracts.Evidence, error) {
			var empty contracts.Evidence
			tenant, _ := ctx.Value(tenantKey{}).(int)
			if tenant != input.Scope.TenantID || tenant < 1 {
				return nil, empty, errors.New("tenant scope mismatch")
			}
			if err := input.Scope.Validate(); err != nil {
				return nil, empty, err
			}
			ctx, cancel := context.WithTimeout(ctx, 8*time.Second)
			defer cancel()
			if input.Limit == 0 {
				input.Limit = 20
			}
			if input.GroupBy == "" {
				input.GroupBy = "category"
			}
			filters := data.Filters{Category: input.Category, Status: input.Status}
			var out contracts.Evidence
			var err error
			switch name {
			case "dataset_status":
				out, err = repo.DatasetStatus(ctx, input.Scope)
			case "incidents_summary":
				out, err = repo.IncidentsSummary(ctx, input.Scope, input.GroupBy, input.Limit, filters)
			case "incidents_timeseries":
				out, err = repo.IncidentsTimeseries(ctx, input.Scope, filters)
			case "incidents_search":
				out, err = repo.IncidentsSearch(ctx, input.Scope, input.Text, input.Limit, input.Cursor, filters)
			case "incident_detail":
				out, err = repo.IncidentDetail(ctx, input.Scope, input.IncidentID)
			case "resolution_statistics":
				out, err = repo.ResolutionStatistics(ctx, input.Scope, filters)
			case "knowledge_search":
				if input.Limit > 5 {
					input.Limit = 5
				}
				out, err = knowledge(ctx, repo, input)
			}
			return nil, out, err
		})
	}
	transport := mcp.NewStreamableHTTPHandler(func(r *http.Request) *mcp.Server { return server }, &mcp.StreamableHTTPOptions{Stateless: true, JSONResponse: true})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if token == "" || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+token)) != 1 {
			http.Error(w, "Unauthorized", 401)
			return
		}
		tenant, err := strconv.Atoi(r.Header.Get("X-Tenant-ID"))
		if err != nil || tenant < 1 || tenant > 5 {
			http.Error(w, "Invalid tenant", 403)
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, 65536)
		transport.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), tenantKey{}, tenant)))
	})
}
