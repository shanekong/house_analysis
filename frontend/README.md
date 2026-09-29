# 初版前端

这是一个无构建依赖的只读 MVP，用于先验证信息架构和查看链路。当前包含：

- 小区观察池与名称搜索
- 小区核心信息卡片
- 数据完整性审计
- 关联数据数量概览

启动方式：

```bash
cd frontend
python3 -m http.server 4173
```

浏览器打开 <http://localhost:4173>。页面通过 `http://localhost:8787/api/v1` 从 FastAPI 获取数据，不再依赖本地数据文件；页面不会把缺失数据渲染成 0 或虚构值。
