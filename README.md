# 杭州购房决策分析

面向个人自用的杭州住宅购房决策工具。项目优先解决“买得起什么、哪里更适合、房子值不值、风险是什么、何时行动”，而不只展示挂牌均价。

当前阶段：工程与治理底座收尾、耀江文鼎苑试点闭环完成。前端已可查阅 10 条历史成交和 10 条当前挂牌观察，其中 4 条来自透明售房网公开小区页；西湖区全量主数据、教育交通配套及市场指标仍未完成，暂不能用于确定性购房结论。

- [需求调研与 MVP 建议](docs/需求调研.md)
- [杭州购房政策汇总（截至 2026-09-19）](docs/杭州购房政策汇总_2026-09-19.md)
- [西湖区教育与学区调研（2026阶段一）](docs/西湖区教育与学区调研_2026-09-19.md)
- [西湖区全量数据库与应用实施计划](docs/实施计划.md)
- [当前进度与下一步](docs/STATUS.md)
- [数据流程与开源项目方法调研（2026-09-29）](docs/数据源与开源项目调研_2026-09-29.md)

## 本地数据库

首版数据底座位于 `backend/`，Mac 本地默认使用 SQLite，不需要安装数据库服务；生产环境可通过 `HOUSE_DATABASE_URL` 切换至 MySQL 8.x。

```bash
cd backend
uv sync
uv run house-db init-db
uv run house-db seed-reference
uv run house-db quality-report
```

核验小区并导入经人工审核的市场快照：

```bash
uv run house-db verify-community <community_id> --address <address> --longitude <lng> --latitude <lat> --market-area <name> --source-code <source> --source-url <url> --source-external-id <id>
uv run house-db set-community-completion-year <community_id> <year> --source-code <source> --source-url <url>
uv run house-db import-market-snapshot data/snapshots/5i5j_yaojiang_wendingyuan_2026-09-29.json --source-code woaiwojia_public
uv run house-db import-market-snapshot data/snapshots/tmsf_yaojiang_wendingyuan_2026-09-29.json --source-code tmsf_public
```

链家直连若返回贝壳安全中心拦截页，命令会输出 `status: blocked` 并停止，不会把拦截页写入数据库。可在正常浏览器中打开目标二手房列表，使用“网页，完整”保存 HTML，然后导入：

```bash
uv run house-db import-lianjia-html <community_id> /path/to/lianjia-page.html \
  --source-url https://hz.lianjia.com/ershoufang/c<lianjia-community-id>/
```

该入口会保存原始 HTML 的 SHA-256、来源 URL 和解析版本，并按链家房源编号幂等更新挂牌记录。项目不会使用代理池、浏览器指纹伪装或验证码破解绕过访问控制。

透明售房网支持公开小区详情页低频直连；若返回阿里云 WAF 挑战会立即熔断。正常浏览器可访问时，保存完整 HTML 后通过同一条规范化链路导入：

```bash
uv run house-db collect-tmsf-community <community_id> \
  https://www.tmsf.com/esf/xq_index_<tmsf-community-id>.htm
uv run house-db import-tmsf-html <community_id> /path/to/tmsf-community.html \
  --source-url https://www.tmsf.com/esf/xq_index_<tmsf-community-id>.htm
```

杭州二手房交易监管服务平台公开旧域名目前不可解析。`collect-hangzhou-official` 会低频探测旧公开 JSON 接口并明确返回 `unavailable`，不会把透明售房网数据伪装成官方平台直采数据。

按来源优先级执行一次统一更新：

```bash
uv run house-db update-community-market <community_id> \
  --lianjia-url <public-listing-url> \
  --woaiwojia-snapshot data/snapshots/<reviewed-5i5j-snapshot>.json \
  --tmsf-url https://www.tmsf.com/esf/xq_index_<tmsf-community-id>.htm \
  --tmsf-snapshot data/snapshots/<reviewed-tmsf-snapshot>.json
```

每个来源独立返回 `succeeded`、`blocked`、`failed` 或 `skipped`。链家触发风控后只熔断链家步骤，后续来源继续执行；未取得或未审核的快照必须保持 `skipped`，不能用猜测数据补齐。

导入经审核的小区 CSV：

```bash
cp data/import_templates/communities.csv /tmp/communities.csv
# 填写 CSV 后执行：
uv run house-db import-communities /tmp/communities.csv
```

运行数据库测试：

```bash
uv run python -m unittest discover -s tests -v
```
## 开发服务管理

```bash
./dev.sh start
```

支持：

```bash
./dev.sh start      # 启动前端与后端
./dev.sh status     # 查看状态
./dev.sh restart    # 重启前端与后端
./dev.sh stop       # 停止前端与后端
./dev.sh check      # 检查环境并运行后端测试
./dev.sh logs       # 查看最近日志
```

脚本会同时启动前端静态服务和后端只读 API：前端默认 `4173`，后端默认 `8787`；端口、PID 和日志保存在 `.dev/`。

后端当前提供：

```text
GET /api/health
GET /api/communities
GET /api/communities/:id
GET /api/communities/:id/quality
GET /api/communities/:id/market
```
