# course-agent 数据模型设计

> 约定：数据库使用 PostgreSQL 16 + pgvector，缓存使用 Redis 7，字段命名 snake_case。所有"个人数据"表均含 `user_id` 外键，作为权限隔离的强制条件。

## 1. 表清单与关系

```
users 1 ── N schedules N ── 1 courses
users 1 ── N course_documents 1 ── N document_chunks
users 1 ── N study_plans 1 ── N study_plan_items
```

## 2. 表结构

### users 用户表

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | INTEGER | PK, 自增 | |
| username | VARCHAR(50) | UNIQUE, NOT NULL | 登录名 |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt 哈希 |
| name | VARCHAR(50) | NOT NULL | 姓名 |
| role | VARCHAR(10) | DEFAULT 'student' | student / admin |
| student_no | VARCHAR(20) | UNIQUE, 可空 | 学号 |
| created_at | DATETIME | NOT NULL | |

### courses 课程表

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| code | VARCHAR(20) | UNIQUE, NOT NULL | 课程编号 |
| name | VARCHAR(100) | NOT NULL | 课程名 |
| teacher | VARCHAR(50) | | 教师 |
| credit | DECIMAL(2,1) | | 学分 |
| semester | VARCHAR(20) | | 学期，如 2026-2027-1 |
| description | TEXT | | 课程简介 |

### schedules 课表记录表

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| user_id | INTEGER | FK → users, NOT NULL | **权限隔离关键字段** |
| course_id | INTEGER | FK → courses, NOT NULL | |
| weekday | TINYINT | NOT NULL | 1-7（周一至周日） |
| start_period | TINYINT | NOT NULL | 起始节次 |
| end_period | TINYINT | NOT NULL | 结束节次 |
| week_start | SMALLINT | NOT NULL | 起始周 |
| week_end | SMALLINT | NOT NULL | 结束周 |
| location | VARCHAR(100) | | 教室 |

### course_documents 课程资料表

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| user_id | INTEGER | FK → users, NOT NULL | 上传者 |
| course_id | INTEGER | FK → courses, 可空 | 可选关联课程 |
| filename | VARCHAR(255) | NOT NULL | 原始文件名 |
| file_path | VARCHAR(500) | NOT NULL | 存储路径 |
| file_type | VARCHAR(20) | | pdf / docx / txt / md |
| status | VARCHAR(20) | DEFAULT 'pending' | pending / processing / ready / failed |
| created_at | DATETIME | | |

### document_chunks 文档切片表（RAG）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK | |
| document_id | INTEGER | FK → course_documents, NOT NULL | |
| chunk_index | INTEGER | NOT NULL | 切片序号 |
| content | TEXT | NOT NULL | 切片文本 |
| search_text | TEXT | NOT NULL | Jieba 分词后的全文检索文本 |
| embedding | VECTOR(512) | | BGE 查询/文档向量 |

### study_plans 学习计划表

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| user_id | INTEGER | FK → users, NOT NULL | |
| title | VARCHAR(200) | NOT NULL | 计划标题 |
| goal | TEXT | | 目标描述 |
| content | TEXT | NOT NULL | 计划全文（Markdown） |
| status | VARCHAR(20) | DEFAULT 'active' | active / completed / archived |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

### study_plan_items 计划子项表（可选）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| plan_id | INTEGER | FK → study_plans, NOT NULL | |
| item_order | INTEGER | | 排序 |
| title | VARCHAR(200) | NOT NULL | |
| content | TEXT | | |
| is_done | BOOLEAN | DEFAULT FALSE | |
| due_date | DATE | | |

## 3. 设计要点

### 3.1 权限隔离（N1）
- 个人数据表（schedules / course_documents / study_plans）均带 `user_id`
- MCP 工具内部强制 `WHERE user_id = 当前登录用户`，禁止跨用户查询
- 实现方式：FastAPI 依赖注入解析 JWT → 得到当前 user_id → 传入工具层

### 3.2 RAG 存储（N2）
- `document_chunks.content` 保存原文，`search_text` 保存 Jieba `cut_for_search` 结果，`embedding` 使用 pgvector `VECTOR(512)`。
- pgvector HNSW 索引参数为 `m=24`、`ef_construction=200`，查询会话使用 `hnsw.ef_search=100`；全文召回使用 `to_tsvector('simple', search_text)` 上的 GIN 索引。
- 检索先做 Query Rewrite，再执行 pgvector 向量召回与 PostgreSQL `tsvector/ts_rank_cd` 关键词召回，经 RRF（`K=60`）和可选 Rerank 后，按单文档最多 2 段去重并返回 Top-10。
- Redis 缓存 Query Rewrite 10 分钟、最终检索结果 60 秒；文档变更时按用户失效缓存。Rerank 未配置或失败时保持 RRF 顺序。

### 3.3 模拟数据（N4）
- 预置 2-3 个学生账号（如 student01 / student02，密码同账号名）
- 每个学生 8-12 条课表记录
- 1-2 份课程资料样例（Markdown 即可，方便演示 RAG）
