# 初版服务架构

```text
Web（当前原生 JS；后续可迁移 React/Vite）
              │ HTTP/JSON（CORS）
小程序（后续复用同一 API 契约）
              │
              ▼
FastAPI + Uvicorn（backend/src/house_analysis/server.py）
              │ SQLAlchemy
              ▼
SQLite（本地）/ MySQL 8（部署）
```

后端是独立服务，不由前端进程托管。`dev.sh` 负责本地开发时同时启动两者，并维护 PID、端口和日志。

API 采用 `/api/v1` 作为稳定版本前缀，同时保留 `/api` 兼容路径：

- `GET /health`
- `GET /api/v1/communities`
- `GET /api/v1/communities/{id}`
- `GET /api/v1/communities/{id}/quality`
- `GET /api/v1/communities/{id}/market`：分开返回历史成交与当前挂牌，并携带来源、数据日期和新鲜度状态

小程序不应直接访问数据库，未来只需通过 HTTPS 域名调用同一组版本化接口。部署到云托管时，SQLite 应替换为 MySQL，配置通过环境变量注入。
