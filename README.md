# 统一资产管理系统

一个完整的企业资产管理系统，包含前后端全栈实现。

## 技术栈

### 后端
- **FastAPI** - 高性能 Python Web 框架
- **SQLAlchemy** - ORM 数据库操作
- **SQLite** - 轻量级数据库（可切换 PostgreSQL）
- **JWT** - 用户认证
- **QRCode** - 二维码生成

### 前端
- **React 18** + **TypeScript**
- **Ant Design** - UI 组件库
- **Recharts** - 数据可视化
- **Zustand** - 状态管理
- **React Router** - 路由管理
- **TailwindCSS** - 样式工具

## 功能特性

- ✅ 用户认证（登录/注册）
- ✅ 资产录入（自动生成编码和二维码）
- ✅ 资产台账管理（搜索/筛选/分页）
- ✅ 资产领用/归还
- ✅ 资产盘点任务
- ✅ 折旧计算（直线法/双倍余额递减法/年数总和法）
- ✅ 资产统计看板
- ✅ 生命周期时间轴

## 快速启动

### 1. 启动后端

```bash
cd backend

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Mac/Linux

# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

后端将运行在：http://localhost:8000
API 文档：http://localhost:8000/docs

### 2. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端将运行在：http://localhost:5173

## 默认账号

- 用户名：`admin`
- 密码：`admin123`

（首次运行时会自动创建管理员账号）

## 项目结构

```
asset-management/
├── backend/
│   ├── app/
│   │   ├── api/          # API 路由
│   │   ├── models/       # 数据模型
│   │   ├── schemas/      # Pydantic 模式
│   │   ├── services/     # 业务服务
│   │   ├── config.py     # 配置
│   │   └── database.py   # 数据库连接
│   ├── main.py           # 应用入口
│   └── requirements.txt  # Python 依赖
└── frontend/
    ├── src/
    │   ├── components/   # 公共组件
    │   ├── pages/        # 页面组件
    │   ├── services/     # API 服务
    │   ├── store/        # 状态管理
    │   ├── types/        # TypeScript 类型
    │   └── App.tsx       # 应用入口
    └── package.json      # Node 依赖
```

## API 端点

### 认证
- `POST /api/auth/login` - 用户登录
- `POST /api/auth/register` - 用户注册
- `GET /api/auth/me` - 获取当前用户

### 资产管理
- `GET /api/assets` - 获取资产列表
- `POST /api/assets` - 创建资产
- `GET /api/assets/{id}` - 获取资产详情
- `PUT /api/assets/{id}` - 更新资产
- `POST /api/assets/{id}/checkout` - 领用资产
- `POST /api/assets/{id}/return` - 归还资产
- `GET /api/assets/statistics` - 资产统计

### 盘点管理
- `POST /api/inventory/tasks` - 创建盘点任务
- `GET /api/inventory/tasks` - 获取盘点任务列表
- `GET /api/inventory/tasks/{id}/items` - 获取盘点明细
- `PUT /api/inventory/items/{id}` - 更新盘点结果

## 开发说明

### 添加新资产类别
在 `backend/app/models/asset.py` 的 `AssetCategory` 枚举中添加。

### 修改折旧算法
在 `backend/app/services/depreciation.py` 中修改计算逻辑。

### 自定义主题色
在 `frontend/src/App.tsx` 中修改 `colorPrimary` 配置。

## License

MIT