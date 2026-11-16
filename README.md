# 05-tiercraft（筑层）

筑层 — 数仓分层建设台：贴源入仓 → 明细清洗标准化 → 汇总落表 → 层间行数/键对账。

**不是** 多源 Feed 归并，**不是** 作业依赖编排，**不是** CDC 变更流按序落库，**不是** 质检隔离签发。
**也不是** 报表看板 / CRUD 后台 / 电商订单前台 / OA 工单。

## 启动

```bash
docker compose up --build
```

本地开发：

```bash
# 后端
cd backend
pip install -r requirements.txt
set DATA_DIR=..\data
uvicorn app.main:app --reload --port 10500

# 前端
cd frontend
npm install
npm run dev
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5500 |
| 接口 | http://localhost:10500 |

## 主链

登记主题域 → 贴源层装载夹具 → 明细层清洗标准化 → 汇总层聚合 → 层间对账报告与各层列表数字同源

## 对账差异键与按键重算

对账按「业务日+门店编码」逐键比较明细聚合与汇总，不只比总数：

- **差异清单物化**：每次生成对账报告，同事务写入 `reconcile_diff_lists`（按报告 id 一对一）与 `reconcile_diff_keys`（业务日、门店编码、差异类型、两侧行数与金额、金额差）。报告是快照，刷新或重启后仍可按报告查清单。
- **按键重算入口**：`POST /api/reconcile/{报告id}/recompute` 与「分层任务」里的全量明细到汇总完全分开。`recompute_runs.diff_list_id` 外键挂差异清单，只处理清单内键。
- **写回来源**：每个键都从 `layer_detail` 重新聚合后写回 `layer_summary`，不读取报告里的期望值。
- **提交边界**：逐键独立事务。单键失败只回滚该键，其余已成功键保留；运行状态记「部分失败」，`recompute_items` 逐键列出成功/失败与前后值。
- **同源**：差异清单、重算报告、汇总写回与当前对账状态都由 `compare_layers()` 派生；报告状态是生成时快照，页面另示按现场派生的当前状态。

## 界面约定

页面文案全部中文；分层称「贴源层 / 明细层 / 汇总层」，界面不出现英文缩写站名。
