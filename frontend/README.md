# DataMind — Frontend (chat)

Chat en español sobre incidentes municipales (Gueo/Delta). Vite + React + TypeScript, sin dependencias extra.

## Requisitos

- Backend corriendo en `http://127.0.0.1:8001` (carpeta `backend/`, no se toca desde aquí).
- Node 20+.

## Cómo correrlo

```bash
npm install
npm run dev      # http://localhost:5173
```

El backend ya permite CORS desde `http://localhost:5173`.

## Configuración

| Variable       | Default                   | Qué hace                                  |
| -------------- | ------------------------- | ----------------------------------------- |
| `VITE_API_URL` | `http://127.0.0.1:8001`   | Base del backend. Vacío = rutas relativas (usan el proxy de Vite en dev). |

Copia `.env.example` a `.env` y ajusta si el backend corre en otro host.

## Qué incluye

- Chat con streaming palabra por palabra (`POST /ask`, parseo SSE vía `fetch` + reader).
- Estado «consultando datos…» mientras llega `meta`, luego deltas en vivo.
- Panel de fuentes colapsable por respuesta (tool, filtros, nº documentos).
- Gráficos SVG propios desde `msg.chart` (barras y línea, sin librerías).
- Historial lateral (`GET /conversations`, abrir, nueva, `conversation_id` en `localStorage`).
- Tema oscuro/claro, responsive, `prefers-reduced-motion` respetado.
- 4 preguntas sugeridas iniciales (conteo por estado, ranking por categoría, tiempos por grupo, evolución mensual).

## Build

```bash
npm run build   # tsc + vite build → dist/
npm run preview # sirve dist/ local
```
