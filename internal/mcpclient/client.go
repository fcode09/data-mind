// Package mcpclient uses the official SDK rather than a proprietary JSON endpoint.
package mcpclient

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/fcode09/data-mind/internal/contracts"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"net/http"
	"strconv"
	"time"
)

type Client struct{ URL, Token string }
type authTransport struct {
	base   http.RoundTripper
	token  string
	tenant int
}

func (t authTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	copy := r.Clone(r.Context())
	copy.Header = r.Header.Clone()
	copy.Header.Set("Authorization", "Bearer "+t.token)
	copy.Header.Set("X-Tenant-ID", strconv.Itoa(t.tenant))
	return t.base.RoundTrip(copy)
}
func (c Client) Call(ctx context.Context, name string, scope contracts.Scope, args map[string]any) (contracts.Evidence, error) {
	var evidence contracts.Evidence
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	transport := &mcp.StreamableClientTransport{Endpoint: c.URL, HTTPClient: &http.Client{Transport: authTransport{http.DefaultTransport, c.Token, scope.TenantID}, Timeout: 16 * time.Second}, DisableStandaloneSSE: true, MaxRetries: -1}
	client := mcp.NewClient(&mcp.Implementation{Name: "data-mind-api", Version: "2.0.0"}, nil)
	session, err := client.Connect(ctx, transport, nil)
	if err != nil {
		return evidence, err
	}
	defer session.Close()
	if args == nil {
		args = map[string]any{}
	}
	args["scope"] = scope
	result, err := session.CallTool(ctx, &mcp.CallToolParams{Name: name, Arguments: args})
	if err != nil {
		return evidence, err
	}
	if result.IsError {
		return evidence, errors.New("data tool failed")
	}
	var payload []byte
	if result.StructuredContent != nil {
		payload, err = json.Marshal(result.StructuredContent)
	} else if len(result.Content) > 0 {
		if text, ok := result.Content[0].(*mcp.TextContent); ok {
			payload = []byte(text.Text)
		}
	}
	if err != nil {
		return evidence, err
	}
	err = json.Unmarshal(payload, &evidence)
	return evidence, err
}
