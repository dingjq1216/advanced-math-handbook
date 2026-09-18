# 附录 I　数值与符号计算工具速查

```text
    附录 I 想算 X -> 该用哪个函数

    ┌───────────────────────────────────────────────────────────────────────┐
    │ 你想算                     │ 第一选择                                 │
    ├────────────────────────────│──────────────────────────────────────────┤
    │ 定积分(光滑)               │ scipy.integrate.quad                     │
    │ 判定是否初等               │ sympy.integrate                          │
    │ Lyapunov/Riccati           │ scipy.linalg.solve_*                     │
    │ 稳定子空间                 │ scipy.linalg.schur                       │
    │ 泛化/概率                  │ scipy.stats + 手推                       │
    │ 优化/KKT                   │ scipy.optimize.minimize                  │
    │ 随机过程采样               │ numpy.random + SDE                       │
    │ 符号推导                   │ sympy (limit/series)                     │
    └───────────────────────────────────────────────────────────────────────┘
```

```text
    附录 I numpy 常用函数（算什么 / 函数 / 坑）

    ┌──────────────────────────────────────────────────────────────────────────┐
    │ np.linalg.solve(A,b)   一般线性解   坑：先查 cond(A)                     │
    │ np.linalg.eig(A)       特征值       坑：不排序，别当 schur               │
    │ np.linalg.svd(A)       奇异值       坑：比 eig(A^T A) 稳                 │
    │ np.polyfit(x,y,deg)    多项式拟合   坑：高次 Runge 震荡                  │
    │ np.random.default_rng  可复现随机   坑：别用旧 seed                      │
    │ np.kron(A,B)           克罗内克     坑：解矩阵方程别手拉直               │
    └──────────────────────────────────────────────────────────────────────────┘
```

```text
    附录 I scipy + sympy 常用函数（算什么 / 函数 / 坑）

    ┌──────────────────────────────────────────────────────────────────────────┐
    │ scipy.integrate.quad      定积分     坑：端点奇异掉两阶                  │
    │ scipy.linalg.solve_lyapunov  Lyapunov  坑：解完查 P>0                    │
    │ scipy.linalg.solve_continuous_are CARE 坑：R 须正定                      │
    │ scipy.linalg.schur(H)      稳定子空间  坑：取左半平面 n 个               │
    │ scipy.optimize.minimize    有约束优化  坑：LICQ 满足才 KKT               │
    │ scipy.stats.*              分布/检验  坑：重尾套 CLT 失效                │
    │ sympy.integrate            符号积分   坑：返 Integral 是 U               │
    │ sympy.sympify              符号构造   坑：须传 locals                    │
    └──────────────────────────────────────────────────────────────────────────┘
```

> **定位　这一章是"上机"的索引：你想算什么，直接查对应的函数，再看它右边那栏的坑。** 覆盖 numpy / scipy / sympy 三件套。符号结论用 sympy 推，数值结果用 scipy 算，两者交叉验证（见附录 B / 附录 G）。

> **铁律一　先判"该符号还是该数值"。** 要解析形式、要条件、要反例→sympy；要一个数、要大规模、要画图→scipy/numpy。两者结论不一致时，通常是你的假设没对齐（如漏了 `positive=True`）。

> **铁律二　矩阵方程别手拉直。** 任何 $AX+XB=C$、Lyapunov、Riccati 都用 `scipy.linalg` 的专用函数，不要自己 `np.kron` 拉直成 $n^{2}$ 维去 `solve`——代价从 $O(n^{3})$ 暴涨到 $O(n^{6})$（附录 F 铁律）。

> **铁律三　精度看条件数 / sep，不看残差。** `solve` 返回残差小不代表解准（附录 F ②）；条件数大的矩阵，结果不可信。

## I.1　想算积分

| 你想算 | 函数 | 坑 |
|---|---|---|
| 一元定积分（光滑） | `scipy.integrate.quad` | 端点有 $\ln$/极点奇异时精度掉两阶（附录 B B.4）——换元或转 `mpmath` tanh-sinh |
| 二重 / 三重积分 | `scipy.integrate.dblquad` / `tplquad` | 积分域写成可调用函数，别硬套矩形 |
| 振荡积分 $\int\sin(kx)f(x)$ | `quad` + `weight='sin'` | 不设权重会被迫加密，慢且不准 |
| 符号积分 / 判定是否初等 | `sympy.integrate` | 返回 `Integral` 是 U（未判定）不是 N（真积不出）；加 `assumptions` 或 `meijerg=True` |
| 未赋值积分想当数值救场 | `float(sympy.Integral(...).subs(...))` | 仅当能数值化时有效（附录 B B.5.5） |

> **陷阱　端点奇异当成 bug**　$\int_{0}^{1}\ln(\sin x)\,dx$ 端点是对数奇异，自适应 quad 退化两阶是**理论预期**不是数值错误。补救：变量替换消奇点，或 `mpmath.quad` 配 `tanhsinh`。

## I.2　想解矩阵方程（附录 F 的"计算器"）

| 方程 | scipy 函数 | 坑 |
|---|---|---|
| $AX+XB=C$ | `scipy.linalg.solve_sylvester(A,B,C)` | 要求 $\lambda_{i}(A)+\lambda_{j}(B)\ne 0$，否则无解 |
| $A^{T}P+PA=-Q$ | `scipy.linalg.solve_lyapunov(A,Q)` | $A$ 稳定且 $Q\succ 0$ 才得 $P\succ 0$；解完**必须查 `np.all(np.linalg.eigvalsh(P)>0)`** |
| CARE（连续 LQR） | `scipy.linalg.solve_continuous_are(A,B,Q,R)` | **$R$ 必须正定**，奇异时 `inv(R)` 崩溃；要求 $(A,B)$ 可镇定 |
| DARE（离散 LQR） | `scipy.linalg.solve_discrete_are` | 用 QZ 辛铅笔，离散/连续别混 |
| 一般线性 $Ax=b$ | `numpy.linalg.solve` | 先查 `np.linalg.cond(A)`，条件数大结果不可信 |

> **陷阱　`inv(R)` 直接写**　LQR 的 $R$ 一旦在模型里"某个通道不花代价"就奇异，CARE 退化成奇异 Riccati，`solve_continuous_are` 抛错。工程上要么加小正则 $\varepsilon I$，要么降到 $R$ 零空间。

## I.3　想算特征值 / 分解

| 你想算 | 函数 | 坑 |
|---|---|---|
| 全部特征值 | `numpy.linalg.eig` | 返回不排序；要稳定子空间用 `scipy.linalg.schur` |
| Schur / 稳定不变子空间（CARE 核心） | `scipy.linalg.schur(H)` | Hamilton 矩阵左半平面 $n$ 个特征值 → 稳定解 $P=X_{2}X_{1}^{-1}$ |
| 广义特征值（辛铅笔） | `scipy.linalg.qz` | DARE 用，别用普通 `eig` |
| SVD | `numpy.linalg.svd` | 大矩阵比 `eig(A^T A)` 稳（避免平方条件数） |

> **陷阱　`eig` 当 `schur` 用**　取 CARE 稳定解必须取 Hamilton 矩阵的**稳定不变子空间**，普通 `eig` 排序后直接取前 $n$ 个会取到不稳定解，闭环发散（附录 F ④）。

## I.4　想拟合 / 优化

| 你想算 | 函数 | 坑 |
|---|---|---|
| 多项式拟合 | `numpy.polyfit(x,y,deg)` | 高次（>10）出现 Runge 震荡；改用样条 `scipy.interpolate` |
| 非线性最小二乘 | `scipy.optimize.least_squares` | 给雅可比比数值微分快且稳 |
| 有约束优化 | `scipy.optimize.minimize(method='SLSQP')` | 约束规范（LICQ）满足才有 KKT 必要（附录 E E.8） |
| 标量寻根 | `scipy.optimize.root` / `brentq` | `brentq` 要求区间端点异号，先画图定位 |

> **陷阱　高次 `polyfit` 当万能**　等距节点高次多项式必震荡（Runge 现象）。数据多时改用分段样条或降维 + 基函数。

## I.5　想符号推导（sympy）

| 你想算 | 函数 | 坑 |
|---|---|---|
| 极限 / 级数展开 | `sympy.limit` / `series` | 多点展开要指定 `x0` 与 `n`；条件收敛重排改变和（附录 E E.2） |
| 解方程 | `sympy.solve` / `solveset` | `solve` 返回列表，`solveset` 返解集；高次可能空 |
| 不定积分判定 | `sympy.integrate` + `sympy.NonElementaryIntegral` | 区分 N（真积不出）与 U（没假设对）；`sympify` 必须传 `locals` 否则符号错位 |
| 矩阵符号运算 | `sympy.Matrix` | 与 numpy 混用要先 `.evalf()` |

> **陷阱　`sympify` 不传 `locals`**　`sympy.sympify("x**2")` 造出的 `Symbol("x")` 与 `Symbol("x", real=True)` 是**不同对象**，积分时把被积函数当成常数→结果错。务必 `locals={"x": x}`。

## I.6　想生成随机 / 统计

| 你想算 | 函数 | 坑 |
|---|---|---|
| 可复现随机 | `numpy.random.default_rng(seed)` | 别用旧 `np.random.seed`（全局状态难追踪） |
| 分布采样 / 概率密度 | `scipy.stats.norm` / `rv_continuous` | 重尾分布（如 Pareto $\alpha\le 2$）方差无穷，套 CLT 失效（附录 D / 附录 E E.6） |
| 假设检验 / 置信区间 | `scipy.stats.ttest_*` / `bootstrap` | 覆盖率才是能证伪的量（第 36.6.4 节），别只看 p 值 |

> **陷阱　重尾硬套 CLT**　样本量再大，方差无穷的分布极限非正态甚至不收敛。先查矩是否存在（附录 E E.6 的 Markov 族）。

## I.7　出口表：问题 → 函数 → 章节

| 你想算 | 第一选择 | 交叉章节 |
|---|---|---|
| 定积分 | `scipy.integrate.quad` | 附录 B / 附录 C |
| 判定是否初等可积 | `sympy.integrate` | 附录 B |
| Lyapunov / Riccati | `scipy.linalg.solve_*` | 附录 F |
| 稳定子空间 | `scipy.linalg.schur` | 附录 F |
| 泛化界 / 概率 | `scipy.stats` + 手推 | 附录 D / 第 35 章 |
| 优化 / KKT | `scipy.optimize.minimize` | 附录 E / 第 25 章 |
| 随机过程采样 | `numpy.random` + SDE 格式 | 附录 E / 第 29 章 |
