# Vehicles API

API pública, somente-leitura, com **1.000.000 de veículos fictícios** (24 campos: marca, modelo, ano,
combustível, potência, preço, consumo, país de origem, nota de segurança...).
Stack: Python + Starlette + SQLite. Sem autenticação. Documentação interativa em `/docs`.

## Rodar localmente
```bash
pip install -r requirements.txt
python build_db.py            # cria data/vehicles.db (~25 s)
uvicorn app.main:app --port 8000
# http://localhost:8000/docs
```

## Rodar com Docker
```bash
docker build -t vehicles-api .
docker run -p 8000:8000 vehicles-api
```

## Endpoints
| Rota | O que faz |
|---|---|
| `GET /vehicles` | Lista com filtros, ordenação e paginação |
| `GET /vehicles/{id}` · `/vehicles/vin/{vin}` | Um veículo |
| `GET /vehicles/random?n=5` | Veículos aleatórios |
| `GET /facets` | Valores válidos dos filtros + faixas (ano, preço, hp) |
| `GET /models?make=Toyota` | Modelos e contagem |
| `GET /stats?group_by=make` | Médias/min/max de preço, hp, consumo (aceita os mesmos filtros) |
| `GET /health` | Status |

**Filtros** (`/vehicles` e `/stats`): `make, model, vehicle_type, fuel_type, transmission, drivetrain,
origin_country, assembly_country, exterior_color` (vários valores com vírgula, sem diferenciar
maiúsculas), `year, year_min, year_max, price_min, price_max, hp_min, hp_max, range_min,
mpg_city_min, mpg_highway_min, safety_min, cylinders, doors`.
**Paginação/ordem**: `page, limit (máx 100), sort (vehicle_id|make|model_year|price_usd|horsepower_hp), order, fields`.

```bash
curl "http://localhost:8000/vehicles?make=toyota,kia&fuel_type=hybrid&year_min=2022&sort=price_usd&order=desc&limit=5&fields=make,model,model_year,price_usd"
curl "http://localhost:8000/stats?group_by=fuel_type"
```
Resposta de lista: `{"data":[...],"meta":{"page","limit","total","total_pages"}}`. Erros: `{"error":{"code","message"}}`.

## Configuração (variáveis de ambiente)
- `RATE_LIMIT_PER_MIN` (padrão 120 por IP; `0` desliga)
- `DB_PATH` (padrão `data/vehicles.db`) · `PORT` (Docker, padrão 8000)

## Deploy
O projeto tem Dockerfile, então funciona em Render, Railway, Fly.io, Google Cloud Run etc.:
suba a pasta para um repositório GitHub, crie um serviço web a partir do Dockerfile e pronto.
O banco é gerado no build. Precisa de ~600 MB de disco e ~512 MB de RAM.
