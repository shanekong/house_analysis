# 数据库开发说明

## 数据库选择

- 本地默认：SQLite，文件为 `data/house_analysis.db`。
- 腾讯云生产：MySQL 8.x，通过 `HOUSE_DATABASE_URL` 配置。
- 数据结构变更统一使用 Alembic，禁止手工修改生产表结构。

MySQL 连接示例：

```bash
export HOUSE_DATABASE_URL='mysql+pymysql://user:password@host:3306/house_analysis?charset=utf8mb4'
uv run house-db init-db
```

## 当前表域

- 来源与采集：`data_source`、`ingestion_run`、`raw_snapshot`、`source_record`
- 主数据：`administrative_area`、`market_area`、`community`、`community_alias`
- 小区事实：`community_fact`
- 市场：`market_observation`、`community_market_monthly`
- 教育：`school`、`school_catchment_rule`、`community_school_mapping`
- 配套：`poi`
- 指标与治理：`metric_definition`、`community_metric_snapshot`、`review_task`

## CSV 导入约定

模板在 `data/import_templates/communities.csv`。`source_record_id` 和 `standard_name` 必填；同一来源的 `source_record_id` 重复导入时更新既有实体，不会创建重复小区。

真实外部数据必须先登记 `data_source`，并保留原始来源、观察时间和许可说明。未知值留空，不填 `0`。

## 开放数据候选采集

OpenStreetMap 候选采集器已实现，但首次执行遇到公共 Overpass 服务超时，尚未向正式数据库导入小区：

```bash
uv run house-db collect-osm-xihu
```

导入对象会标记为 `verification_status=pending`，不能直接视为已核验小区。数据使用须显示 `© OpenStreetMap contributors` 并遵守 ODbL 1.0。透明售房网仅保留为人工参考来源，其免责声明限制未经授权复制，因此不执行批量自动采集。

## 单小区完整性审计

可按标准名称输出一个小区的核心字段和关联数据缺口：

```bash
uv run house-db community-quality "耀江文鼎苑"
```

该命令只报告缺失，不会自动填入未经核实的数据。
