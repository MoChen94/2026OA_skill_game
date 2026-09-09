/* 工业运维大屏逻辑：登录门禁 + 15 秒自动刷新 + ECharts */
const { createApp, ref, reactive, onMounted, onBeforeUnmount } = Vue;
const { ElMessage } = ElementPlus;

const STATUS_DOT = {
  PENDING_DISPATCH: '待派发', PENDING_ACCEPT: '待接单', PROCESSING: '处理中',
  PENDING_VERIFY: '待验收', COMPLETED: '已完成', CANCELLED: '已取消',
};

const RootApp = {
  template: `
    <div>
      <div v-if="!user" class="login-wrap">
        <div class="login-card">
          <div class="login-logo">OA协同办公平台 · 数据大屏</div>
          <div class="login-sub">请使用调度员或管理员账号登录</div>
          <el-input v-model="loginForm.username" size="large" placeholder="用户名" style="margin-bottom:14px"></el-input>
          <el-input v-model="loginForm.password" size="large" type="password" show-password placeholder="密码" style="margin-bottom:14px" @keyup.enter="doLogin"></el-input>
          <el-button type="primary" size="large" style="width:100%" :loading="loginLoading" @click="doLogin">进入大屏</el-button>
        </div>
      </div>

      <div v-else class="screen">
        <div class="screen-header">
          <div class="screen-title">协同办公数据大屏</div>
          <div class="screen-clock">{{ nowStr }}</div>
        </div>

        <div class="kpi-strip">
          <div class="kpi-box"><div class="kpi-num">{{ d.device_total }}</div><div class="kpi-label">设备总数</div></div>
          <div class="kpi-box"><div class="kpi-num">{{ d.device_status['运行'] || 0 }}</div><div class="kpi-label">运行中</div></div>
          <div class="kpi-box"><div class="kpi-num warn">{{ d.device_status['告警'] || 0 }}</div><div class="kpi-label">告警设备</div></div>
          <div class="kpi-box"><div class="kpi-num">{{ d.created_today }}</div><div class="kpi-label">今日新增工单</div></div>
          <div class="kpi-box"><div class="kpi-num">{{ d.active_count }}</div><div class="kpi-label">处理中工单</div></div>
          <div class="kpi-box"><div class="kpi-num good">{{ d.completed_today }}</div><div class="kpi-label">今日完成</div></div>
          <div class="kpi-box"><div class="kpi-num warn">{{ d.pending_reviews }}</div><div class="kpi-label">待审核报修</div></div>
        </div>

        <div class="screen-body">
          <div class="panel">
            <div class="panel-title">工单状态分布</div>
            <div class="panel-body"><div ref="statusEl" class="chart"></div></div>
          </div>
          <div class="panel">
            <div class="panel-title">近 7 天工单趋势（新增 / 完成）</div>
            <div class="panel-body"><div ref="trendEl" class="chart"></div></div>
          </div>
          <div class="panel">
            <div class="panel-title">工程师完成排行（近 7 天）</div>
            <div class="panel-body"><div ref="rankEl" class="chart"></div></div>
          </div>
          <div class="panel">
            <div class="panel-title">设备状态分布</div>
            <div class="panel-body"><div ref="deviceEl" class="chart"></div></div>
          </div>
          <div class="panel">
            <div class="panel-title">最新工单</div>
            <div class="panel-body scroll-list">
              <div v-for="o in d.recent_orders" :key="o.id" class="scroll-item">
                <span class="dot" :class="o.status"></span>
                <span class="t">{{ o.order_no }} {{ o.title }}</span>
                <span class="tm">{{ o.created_at.slice(5, 16) }}</span>
              </div>
            </div>
          </div>
          <div class="panel">
            <div class="panel-title">最新报修单</div>
            <div class="panel-body scroll-list">
              <div v-for="r in d.recent_repairs" :key="r.id" class="scroll-item">
                <span class="dot" :class="r.status"></span>
                <span class="t">{{ r.request_no }} {{ r.title }}</span>
                <span class="tm">{{ r.created_at.slice(5, 16) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  data() {
    return {
      user: null,
      loginForm: { username: '', password: '' },
      loginLoading: false,
      d: {
        device_total: 0, device_status: {}, created_today: 0, active_count: 0,
        completed_today: 0, pending_reviews: 0,
        status_counts: [], trend: { labels: [], created: [], completed: [] },
        engineer_ranking: [], recent_orders: [], recent_repairs: [],
      },
      nowStr: '', clockTimer: null, pollTimer: null,
      charts: {},
    };
  },
  methods: {
    api(path) {
      return fetch('/api/v1' + path, {
        headers: { Authorization: 'Bearer ' + localStorage.getItem('oatool_token') },
      }).then(function (r) {
        if (r.status === 401) throw { status: 401 };
        return r.json().then(function (data) {
          if (!r.ok) throw { message: typeof data.detail === 'string' ? data.detail : '请求失败' };
          return data;
        });
      });
    },
    async doLogin() {
      this.loginLoading = true;
      try {
        const res = await fetch('/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.loginForm),
        });
        const data = await res.json();
        if (!res.ok) { ElMessage.error(typeof data.detail === 'string' ? data.detail : '登录失败'); return; }
        localStorage.setItem('oatool_token', data.token);
        this.user = data.user;
        await this.load();
      } catch (e) { ElMessage.error('无法连接服务器'); }
      this.loginLoading = false;
    },
    async restore() {
      if (!localStorage.getItem('oatool_token')) return;
      try {
        const me = await this.api('/auth/me');
        this.user = me;
        await this.load();
      } catch (e) {
        this.user = null;
        localStorage.removeItem('oatool_token');
      }
    },
    async load() {
      try {
        this.d = await this.api('/screen/summary');
        this.renderCharts();
      } catch (e) {
        if (e.status === 401) { this.user = null; localStorage.removeItem('oatool_token'); }
      }
    },
    renderCharts() {
      const colors = ['#409eff', '#e6a23c', '#ff9f43', '#b078ff', '#4cd97b', '#ff6b6b'];
      const mk = (el) => {
        if (!el) return null;
        const k = el.getAttribute('data-chart') || 'c' + Math.random().toString(36).slice(2);
        el.setAttribute('data-chart', k);
        if (!this.charts[k]) this.charts[k] = echarts.init(el);
        return this.charts[k];
      };
      const textStyle = { color: '#7d9cc9' };

      const statusChart = mk(this.$refs.statusEl);
      statusChart && statusChart.setOption({
        color: colors,
        tooltip: { trigger: 'item' },
        legend: { bottom: 0, textStyle },
        series: [{ type: 'pie', radius: ['38%', '62%'], center: ['50%', '44%'],
                   label: { color: '#9cc8ff', formatter: '{b}\\n{c}' }, data: this.d.status_counts }],
      });

      const trendChart = mk(this.$refs.trendEl);
      trendChart && trendChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { bottom: 0, textStyle },
        grid: { left: 40, right: 20, top: 26, bottom: 40 },
        xAxis: { type: 'category', data: this.d.trend.labels, axisLine: { lineStyle: { color: '#2a4a7a' } }, axisLabel: textStyle },
        yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: 'rgba(64,158,255,.15)' } }, axisLabel: textStyle },
        series: [
          { name: '新增', type: 'line', smooth: true, data: this.d.trend.created, itemStyle: { color: '#3fd0ff' }, areaStyle: { opacity: .18 } },
          { name: '完成', type: 'line', smooth: true, data: this.d.trend.completed, itemStyle: { color: '#4cd97b' }, areaStyle: { opacity: .18 } },
        ],
      });

      const rankChart = mk(this.$refs.rankEl);
      rankChart && rankChart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 60, right: 20, top: 16, bottom: 26 },
        xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: 'rgba(64,158,255,.15)' } }, axisLabel: textStyle },
        yAxis: { type: 'category', data: this.d.engineer_ranking.map(function (x) { return x.name; }), axisLabel: textStyle, axisLine: { lineStyle: { color: '#2a4a7a' } } },
        series: [{ type: 'bar', data: this.d.engineer_ranking.map(function (x) { return x.value; }),
                   itemStyle: { borderRadius: [0, 4, 4, 0], color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#1e5fb8' }, { offset: 1, color: '#3fd0ff' }]) },
                   barWidth: 14, label: { show: true, position: 'right', color: '#9cc8ff' } }],
      });

      const deviceChart = mk(this.$refs.deviceEl);
      deviceChart && deviceChart.setOption({
        tooltip: { trigger: 'item' },
        legend: { bottom: 0, textStyle },
        color: ['#4cd97b', '#ff6b6b', '#e6a23c', '#5f7fa8'],
        series: [{ type: 'pie', radius: ['38%', '62%'], center: ['50%', '44%'],
                   label: { color: '#9cc8ff', formatter: '{b}\\n{c} 台' },
                   data: Object.keys(this.d.device_status).map(function (k) { return { name: k, value: this.d.device_status[k] }; }, this) }],
      });
    },
    updateClock() { this.nowStr = new Date().toLocaleString('zh-CN', { hour12: false }); },
  },
  mounted() {
    this.updateClock();
    this.clockTimer = setInterval(this.updateClock, 1000);
    this.restore();
    this.pollTimer = setInterval(() => { if (this.user) this.load(); }, 15000);
    window.addEventListener('resize', () => {
      Object.keys(this.charts).forEach(k => this.charts[k] && this.charts[k].resize());
    });
  },
  beforeUnmount() {
    if (this.clockTimer) clearInterval(this.clockTimer);
    if (this.pollTimer) clearInterval(this.pollTimer);
    Object.keys(this.charts).forEach(k => this.charts[k] && this.charts[k].dispose());
  },
};

const app = createApp(RootApp);
app.use(ElementPlus);
app.mount('#app');
