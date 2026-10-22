FROM golang:1.27.3 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY internal ./internal
COPY apps ./apps
RUN CGO_ENABLED=0 go build -trimpath -o /out/api ./apps/api && CGO_ENABLED=0 go build -trimpath -o /out/mcp ./apps/mcp && CGO_ENABLED=0 go build -trimpath -o /out/worker ./apps/worker
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /out/ /app/
COPY db ./db
CMD ["/app/api"]
