/* OA 前端主应用：登录 / 工作台 / 工单管理 / 设备台账 */

const STATUS_TAG = { PENDING_DISPATCH: 'info', PENDING_ACCEPT: 'warning', PROCESSING: 'primary', PENDING_VERIFY: 'warning', COMPLETED: 'success', CANCELLED: 'danger' };
const PRIORITY_TAG = { P1: 'danger', P2: 'warning', P3: 'primary', P4: 'info' };
const TYPE_TAG = { FAULT: 'danger', INSPECTION: 'warning', MAINTENANCE: 'primary', TASK: 'info' };
const DEVICE_STATUS_TAG = { RUNNING: 'success', ALARM: 'danger', MAINTENANCE: 'warning', OFFLINE: 'info' };

const { createApp, ref, reactive, computed, onMounted, onBeforeUnmount, watch, nextTick } = Vue;
const { ElMessage, ElMessageBox, ElNotification } = ElementPlus;

/* 单文件上传上限（MB），与后端 OATOOL_MAX_UPLOAD_MB 默认值一致 */
const MAX_UPLOAD_MB = 500;

/* 文件大小格式化 */
function fmtSize(n) {
  if (n === null || n === undefined) return '—';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}

/* ---------------- 工作台 ---------------- */
const DashboardView = {
  name: 'DashboardView',
  props: ['user', 'tick'],
  template: `
    <div class="dashboard">
      <div class="kpi-row">
        <div class="kpi-card c1"><div class="kpi-label">今日新增工单</div><div class="kpi-value">{{ summary.created_today }}<span class="kpi-unit">单</span></div></div>
        <div class="kpi-card c2"><div class="kpi-label">待处理工单</div><div class="kpi-value">{{ summary.pending }}<span class="kpi-unit">单</span></div></div>
        <div class="kpi-card c3"><div class="kpi-label">本月已完成</div><div class="kpi-value">{{ summary.completed_month }}<span class="kpi-unit">单</span></div></div>
        <div class="kpi-card c4"><div class="kpi-label">平均处理时长</div><div class="kpi-value">{{ summary.avg_hours }}<span class="kpi-unit">小时</span></div></div>
        <div class="kpi-card c5"><div class="kpi-label">待审核报修</div><div class="kpi-value">{{ summary.pending_reviews }}<span class="kpi-unit">单</span></div></div>
      </div>
      <el-row :gutter="16" class="chart-row">
        <el-col :span="12">
          <el-card shadow="never" class="panel">
            <template #header><span class="panel-title">工单状态分布</span></template>
            <div ref="chartEl" class="chart"></div>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="never" class="panel">
            <template #header><span class="panel-title">设备状态分布</span></template>
            <div class="device-status-list">
              <div v-for="(count, name) in summary.device_status" :key="name" class="device-status-item">
                <span class="device-dot" :class="deviceDotClass(name)"></span>
                <span class="device-status-name">{{ name }}</span>
                <span class="device-status-count">{{ count }} 台</span>
              </div>
              <div v-if="!Object.keys(summary.device_status).length" class="empty-tip">暂无设备</div>
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-card shadow="never" class="panel">
        <template #header><span class="panel-title">最新工单</span></template>
        <el-table :data="summary.recent" stripe size="small">
          <el-table-column prop="order_no" label="工单号" width="150"></el-table-column>
          <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip></el-table-column>
          <el-table-column label="优先级" width="90">
            <template #default="scope"><el-tag :type="PRIORITY_TAG[scope.row.priority]" size="small">{{ scope.row.priority_label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="scope"><el-tag :type="STATUS_TAG[scope.row.status]" size="small">{{ scope.row.status_label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="指派工程师" width="120">
            <template #default="scope">{{ scope.row.assignee_name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="150"></el-table-column>
        </el-table>
      </el-card>
    </div>
  `,
  data() {
    return { summary: { created_today: 0, pending: 0, completed_month: 0, avg_hours: 0, pending_reviews: 0, status_counts: [], device_status: {}, recent: [] }, chart: null, PRIORITY_TAG, STATUS_TAG };
  },
  methods: {
    deviceDotClass(name) {
      return { '运行': 'ok', '告警': 'err', '维修中': 'warn', '停机': 'off' }[name] || 'off';
    },
    async load() {
      try { this.summary = await API.get('/dashboard/summary'); } catch (e) { ElMessage.error(e.message); }
      this.renderChart();
    },
    renderChart() {
      if (!this.$refs.chartEl) return;
      if (!this.chart) this.chart = echarts.init(this.$refs.chartEl);
      const data = this.summary.status_counts.filter(function (s) { return s.count > 0; })
        .map(function (s) { return { name: s.label, value: s.count }; });
      this.chart.setOption({
        tooltip: { trigger: 'item' },
        legend: { bottom: 0 },
        color: ['#909399', '#e6a23c', '#409eff', '#f56c6c', '#67c23a', '#c0c4cc'],
        series: [{ type: 'pie', radius: ['42%', '68%'], center: ['50%', '44%'], label: { formatter: '{b}：{c}' }, data: data }]
      });
    },
    onResize() { if (this.chart) this.chart.resize(); },
  },
  mounted() { this.load(); window.addEventListener('resize', this.onResize); },
  beforeUnmount() { window.removeEventListener('resize', this.onResize); if (this.chart) { this.chart.dispose(); this.chart = null; } },
  watch: { tick() { this.load(); } },
};

/* ---------------- 工单管理 ---------------- */
const OrdersView = {
  name: 'OrdersView',
  props: ['user', 'tick', 'openId'],
  template: `
    <div class="orders">
      <div class="toolbar">
        <el-radio-group v-model="status" size="default" @change="onStatusChange">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="PENDING_DISPATCH">待派发</el-radio-button>
          <el-radio-button label="PENDING_ACCEPT">待接单</el-radio-button>
          <el-radio-button label="PROCESSING">处理中</el-radio-button>
          <el-radio-button label="PENDING_VERIFY">待验收</el-radio-button>
          <el-radio-button label="COMPLETED">已完成</el-radio-button>
          <el-radio-button label="CANCELLED">已取消</el-radio-button>
        </el-radio-group>
        <el-switch v-if="isManager" v-model="mine" active-text="只看与我相关" @change="onStatusChange" style="margin-left:16px"></el-switch>
        <div class="toolbar-right">
          <el-input v-model="keyword" placeholder="搜索标题 / 工单号" clearable style="width:220px" @keyup.enter="search" @clear="search">
            <template #append><el-button @click="search">搜索</el-button></template>
          </el-input>
          <el-button @click="load">刷新</el-button>
          <el-button v-if="user.role === 'ADMIN'" type="danger" plain @click="clearAllOrders">清空全部工单</el-button>
          <el-button v-if="isManager" @click="exportOrders">导出 Excel</el-button>
          <el-button v-if="isManager" type="primary" @click="openCreate">＋ 新建工单</el-button>
        </div>
      </div>

      <el-card shadow="never" class="panel">
        <el-table :data="list" v-loading="loading" stripe>
          <el-table-column label="工单号" width="160">
            <template #default="scope"><a class="link" @click="openDetail(scope.row)">{{ scope.row.order_no }}</a></template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip></el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="scope"><el-tag :type="TYPE_TAG[scope.row.order_type]" effect="light" size="small">{{ scope.row.order_type_label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="优先级" width="90">
            <template #default="scope"><el-tag :type="PRIORITY_TAG[scope.row.priority]" size="small">{{ scope.row.priority_label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="设备" width="160" show-overflow-tooltip>
            <template #default="scope">{{ scope.row.device_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="scope"><el-tag :type="STATUS_TAG[scope.row.status]" size="small">{{ scope.row.status_label }}</el-tag></template>
            </el-table-column>
          <el-table-column label="指派工程师" width="110">
            <template #default="scope">{{ scope.row.assignee_name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="150"></el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="scope"><el-button link type="primary" @click="openDetail(scope.row)">详情</el-button></template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination background layout="total, prev, pager, next" :total="total" :page-size="pageSize" :current-page="page" @current-change="onPage"></el-pagination>
        </div>
      </el-card>

      <!-- 新建工单 / 工程师报修 -->
      <el-dialog v-model="createDlg" :title="isManager ? '新建工单' : '故障报修'" width="560px" :close-on-click-modal="false">
        <el-form label-width="90px">
          <el-form-item label="工单标题" required><el-input v-model="createForm.title" placeholder="如：一号车间输送带异响排查"></el-input></el-form-item>
          <el-form-item label="工单类型"><el-select v-model="createForm.order_type" style="width:100%">
            <el-option label="故障维修" value="FAULT"></el-option>
            <el-option label="巡检" value="INSPECTION"></el-option>
            <el-option label="保养" value="MAINTENANCE"></el-option>
            <el-option label="任务" value="TASK"></el-option>
          </el-select></el-form-item>
          <el-form-item label="关联设备"><el-select v-model="createForm.device_id" clearable placeholder="选择设备" style="width:100%">
            <el-option v-for="d in devices" :key="d.id" :label="d.code + ' ' + d.name" :value="d.id"></el-option>
          </el-select></el-form-item>
          <el-form-item label="优先级"><el-select v-model="createForm.priority" style="width:100%">
            <el-option label="P1 紧急" value="P1"></el-option>
            <el-option label="P2 高" value="P2"></el-option>
            <el-option label="P3 中" value="P3"></el-option>
            <el-option label="P4 低" value="P4"></el-option>
          </el-select></el-form-item>
          <el-form-item v-if="isManager" label="指派工程师"><el-select v-model="createForm.assignee_id" clearable placeholder="不选则创建后待派发" style="width:100%">
            <el-option v-for="e in engineers" :key="e.id" :label="e.real_name + (e.title ? '（' + e.title + '）' : '')" :value="e.id"></el-option>
          </el-select></el-form-item>
          <el-form-item label="工单描述"><el-input v-model="createForm.description" type="textarea" :rows="3" placeholder="描述问题现象、处理要求等"></el-input></el-form-item>
          <el-form-item v-if="isManager" label="附件">
            <div style="width:100%">
              <el-button size="small" @click="pickDraft">＋ 上传附件</el-button>
              <input ref="draftInput" type="file" multiple style="display:none" @change="onDraftPicked">
              <div v-for="f in draftFiles" :key="f.id" class="draft-file">
                <span class="draft-name">{{ f.name }}（{{ fmtSize(f.size) }}）</span>
                <el-button link type="primary" @click="downloadDraft(f)">下载</el-button>
                <el-button link type="danger" @click="removeDraft(f)">删除</el-button>
              </div>
              <div v-if="!draftFiles.length" class="no-perm">可先上传图片/文档，提交工单后自动作为该工单的附件；提交前可下载或删除</div>
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createDlg = false">取消</el-button>
          <el-button type="primary" :loading="creating" @click="submitCreate">{{ isManager ? '创建' : '提交报修' }}</el-button>
        </template>
      </el-dialog>

      <!-- 工单详情 -->
      <el-drawer v-model="drawer" size="600px" :with-header="true">
        <template #header><span class="drawer-title">工单详情</span></template>
        <div v-if="detail" v-loading="detailLoading">
          <div class="detail-head">
            <div class="detail-no">{{ detail.order_no }}</div>
            <div class="detail-title">{{ detail.title }}</div>
            <div class="detail-tags">
              <el-tag :type="STATUS_TAG[detail.status]" size="small">{{ detail.status_label }}</el-tag>
              <el-tag :type="PRIORITY_TAG[detail.priority]" size="small" style="margin-left:6px">{{ detail.priority_label }}</el-tag>
              <el-tag :type="TYPE_TAG[detail.order_type]" effect="plain" size="small" style="margin-left:6px">{{ detail.order_type_label }}</el-tag>
            </div>
          </div>
          <el-steps v-if="detail.status !== 'CANCELLED'" :active="stepIndex" finish-status="success" align-center class="steps">
            <el-step title="待派发"></el-step>
            <el-step title="待接单"></el-step>
            <el-step title="处理中"></el-step>
            <el-step title="待验收"></el-step>
            <el-step title="已完成"></el-step>
          </el-steps>
          <el-alert v-else title="该工单已取消" type="error" :closable="false" show-icon></el-alert>

          <el-descriptions :column="2" border size="small" class="desc">
            <el-descriptions-item label="关联设备">{{ detail.device_name || '—' }}<span v-if="detail.device_location">（{{ detail.device_location }}）</span></el-descriptions-item>
            <el-descriptions-item label="创建人">{{ detail.creator_name }}</el-descriptions-item>
            <el-descriptions-item label="指派工程师">{{ detail.assignee_name || '未指派' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ detail.created_at }}</el-descriptions-item>
            <el-descriptions-item label="完成时间">{{ detail.finish_time || '—' }}</el-descriptions-item>
          </el-descriptions>

          <div class="block-title">工单描述</div>
          <div class="desc-text">{{ detail.description || '无' }}</div>

          <div class="block-title">📎 工单附件</div>
          <div class="attach-bar">
            <el-button size="small" @click="pickAttach">＋ 上传附件</el-button>
            <input ref="attachInput" type="file" multiple style="display:none" @change="onAttachPicked">
            <span class="no-perm" style="margin-left:10px">支持图片与文档，工单相关人员均可查看下载</span>
          </div>
          <div v-if="attachUploading" class="attach-progress">
            <div class="up-name">正在上传附件：{{ attachUploadName }}</div>
            <el-progress :percentage="attachUploadPct" :stroke-width="12" :text-inside="true" striped striped-flow></el-progress>
          </div>
          <div class="file-grid" style="margin-bottom:14px">
            <div class="file-row file-head">
              <div class="f-name">文件名</div>
              <div class="f-size">大小</div>
              <div class="f-uploader">上传人</div>
              <div class="f-time">上传时间</div>
              <div class="f-ops">操作</div>
            </div>
            <div v-for="a in attachments" :key="a.id" class="file-row">
              <div class="f-name"><a class="link" @click="openAttach(a)"><span class="ft-ico" :class="a.is_image ? 'img' : 'doc'">{{ a.is_image ? '图' : '文' }}</span>{{ a.name }}</a></div>
              <div class="f-size">{{ fmtSize(a.size) }}</div>
              <div class="f-uploader">{{ a.uploader_name }}</div>
              <div class="f-time">{{ a.created_at }}</div>
              <div class="f-ops">
                <el-button link type="primary" @click="downloadAttach(a)">下载</el-button>
                <el-button v-if="canDeleteAttach(a)" link type="danger" @click="removeAttach(a)">删除</el-button>
              </div>
            </div>
          </div>
          <div v-if="!attachments.length" class="empty-tip" style="padding:12px 0">暂无附件</div>

          <div v-if="prettyAlarm" class="block-title">📡 数字孪生告警数据</div>
          <pre v-if="prettyAlarm" class="alarm-json">{{ prettyAlarm }}</pre>

          <div class="block-title">流转记录</div>
          <el-timeline>
            <el-timeline-item v-for="(log, i) in logs" :key="i" :timestamp="log.created_at" placement="top">
              <b>{{ log.action_label }}</b> · {{ log.operator_name }}<span v-if="log.detail"> — {{ log.detail }}</span>
            </el-timeline-item>
          </el-timeline>

          <div class="drawer-actions">
            <el-button v-if="can('dispatch')" type="primary" @click="openDispatch">派 单</el-button>
            <el-button v-if="can('accept')" type="success" @click="doAccept">接 单</el-button>
            <el-button v-if="can('complete')" type="primary" @click="openComplete">提交完成</el-button>
            <el-button v-if="can('verify')" type="warning" @click="openVerify">验 收</el-button>
            <el-button v-if="can('cancel')" type="danger" plain @click="openCancel">取消工单</el-button>
          </div>
        </div>
      </el-drawer>

      <!-- 派单 -->
      <el-dialog v-model="dispatchDlg" title="派单" width="420px">
        <el-form label-width="90px">
          <el-form-item label="选择工程师"><el-select v-model="dispatchForm.assignee_id" placeholder="选择工程师" style="width:100%">
            <el-option v-for="e in engineers" :key="e.id" :label="e.real_name + '（' + (e.title || e.dept_name || '—') + '）'" :value="e.id"></el-option>
          </el-select></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dispatchDlg = false">取消</el-button>
          <el-button type="primary" :loading="acting" @click="doDispatch">确认派单</el-button>
        </template>
      </el-dialog>

      <!-- 提交完成 -->
      <el-dialog v-model="completeDlg" title="提交完成" width="520px">
        <el-input v-model="completeForm.result" type="textarea" :rows="4" placeholder="填写处理结果、更换的备件、测试情况等"></el-input>
        <div style="margin-top:12px">
          <el-button size="small" @click="pickComplete">＋ 上传处理附件（可选）</el-button>
          <input ref="completeInput" type="file" multiple style="display:none" @change="onCompletePicked">
          <div v-for="f in completeFiles" :key="f.id" class="draft-file">
            <span class="draft-name">{{ f.name }}（{{ fmtSize(f.size) }}）</span>
            <el-button link type="primary" @click="downloadDraft(f)">下载</el-button>
            <el-button link type="danger" @click="removeDraft(f)">删除</el-button>
          </div>
          <div v-if="!completeFiles.length" class="no-perm">可上传处理后的照片/报告等，随提交一并挂到工单，验收时直接查看</div>
        </div>
        <div v-if="attachUploading" class="attach-progress" style="margin-top:10px">
          <div class="up-name">正在上传：{{ attachUploadName }}</div>
          <el-progress :percentage="attachUploadPct" :stroke-width="12" :text-inside="true" striped striped-flow></el-progress>
        </div>
        <template #footer>
          <el-button @click="completeDlg = false">取消</el-button>
          <el-button type="primary" :loading="acting" @click="doComplete">提交验收</el-button>
        </template>
      </el-dialog>

      <!-- 验收 -->
      <el-dialog v-model="verifyDlg" title="工单验收" width="480px">
        <el-radio-group v-model="verifyForm.passed">
          <el-radio :value="true">验收通过</el-radio>
          <el-radio :value="false">驳回重新处理</el-radio>
        </el-radio-group>
        <el-input v-model="verifyForm.comment" type="textarea" :rows="3" placeholder="验收意见" style="margin-top:12px"></el-input>
        <template #footer>
          <el-button @click="verifyDlg = false">取消</el-button>
          <el-button type="primary" :loading="acting" @click="doVerify">提交</el-button>
        </template>
      </el-dialog>

      <!-- 附件图片预览 -->
      <el-dialog v-model="previewDlg" :title="previewName" width="720px" :close-on-click-modal="false">
        <div style="text-align:center"><img :src="previewUrl" style="max-width:100%;max-height:70vh"></div>
        <template #footer>
          <el-button @click="previewDlg = false">关闭</el-button>
          <el-button type="primary" @click="downloadAttach(previewRow)">下载</el-button>
        </template>
      </el-dialog>

      <!-- 取消 -->
      <el-dialog v-model="cancelDlg" title="取消工单" width="480px">
        <el-input v-model="cancelForm.reason" type="textarea" :rows="3" placeholder="取消原因"></el-input>
        <template #footer>
          <el-button @click="cancelDlg = false">返回</el-button>
          <el-button type="danger" :loading="acting" @click="doCancel">确认取消</el-button>
        </template>
      </el-dialog>
    </div>
  `,
  data() {
    return {
      list: [], total: 0, page: 1, pageSize: 10,
      status: '', mine: false, keyword: '', loading: false,
      devices: [], engineers: [],
      drawer: false, detail: null, logs: [], detailLoading: false,
      attachments: [], previewDlg: false, previewUrl: '', previewName: '', previewRow: null,
      attachUploading: false, attachUploadName: '', attachUploadPct: 0,
      createDlg: false, creating: false, draftFiles: [],
      createForm: { title: '', order_type: 'TASK', device_id: null, priority: 'P3', description: '', assignee_id: null },
      dispatchDlg: false, dispatchForm: { assignee_id: null },
      completeDlg: false, completeForm: { result: '' }, completeFiles: [],
      verifyDlg: false, verifyForm: { passed: true, comment: '' },
      cancelDlg: false, cancelForm: { reason: '' },
      acting: false,
      STATUS_TAG, PRIORITY_TAG, TYPE_TAG,
    };
  },
  computed: {
    isManager() { return this.user.role === 'ADMIN' || this.user.role === 'DISPATCHER'; },
    prettyAlarm() {
      if (!this.detail || !this.detail.alarm_data) return '';
      try { return JSON.stringify(JSON.parse(this.detail.alarm_data), null, 2); } catch (e) { return this.detail.alarm_data; }
    },
    stepIndex() {
      if (!this.detail) return 0;
      const m = { PENDING_DISPATCH: 0, PENDING_ACCEPT: 1, PROCESSING: 2, PENDING_VERIFY: 3, COMPLETED: 5 };
      return m[this.detail.status] !== undefined ? m[this.detail.status] : 0;
    },
  },
  methods: {
    async load() {
      this.loading = true;
      try {
        const params = new URLSearchParams();
        if (this.status) params.set('status', this.status);
        if (this.mine) params.set('mine', '1');
        if (this.keyword) params.set('keyword', this.keyword);
        params.set('page', this.page);
        params.set('page_size', this.pageSize);
        const data = await API.get('/work-orders?' + params.toString());
        this.list = data.items;
        this.total = data.total;
      } catch (e) { if (e.status !== 401) ElMessage.error(e.message); }
      this.loading = false;
    },
    async clearAllOrders() {
      try {
        await ElMessageBox.confirm(
          '将删除全部工单（共 ' + this.total + ' 张，含报修单、流转记录与工单附件），删除后无法恢复，确定清空？',
          '管理员清空确认', { type: 'warning', confirmButtonText: '全部删除', cancelButtonText: '取消' }
        );
      } catch (e) { return; }
      try {
        const r = await API.del('/work-orders/all');
        ElMessage.success('已清空 ' + (r.deleted_orders || 0) + ' 张工单（含报修单 ' + (r.deleted_repairs || 0) + ' 张）');
        this.load();
      } catch (e) { ElMessage.error(e.message); }
    },
    async exportOrders() {
      const params = new URLSearchParams();
      if (this.status) params.set('status', this.status);
      if (this.mine) params.set('mine', '1');
      if (this.keyword) params.set('keyword', this.keyword);
      const q = params.toString();
      try {
        await API.download('/work-orders/export' + (q ? '?' + q : ''));
        ElMessage.success('导出成功');
      } catch (e) { ElMessage.error(e.message); }
    },
    onStatusChange() { this.page = 1; this.load(); },
    search() { this.page = 1; this.load(); },
    onPage(p) { this.page = p; this.load(); },
    async loadDevices() { try { this.devices = await API.get('/devices'); } catch (e) {} },
    async loadEngineers() {
      if (!this.isManager) return;
      try { this.engineers = await API.get('/users?role=ENGINEER'); } catch (e) {}
    },
    async openDetailById(id) {
      this.drawer = true;
      this.detailLoading = true;
      this.detail = null;
      this.logs = [];
      this.attachments = [];
      try {
        this.detail = await API.get('/work-orders/' + id);
        this.logs = await API.get('/work-orders/' + id + '/logs');
        this.loadAttachments();
      } catch (e) { ElMessage.error(e.message); this.drawer = false; }
      this.detailLoading = false;
      this.$emit('consume-open');
    },
    async openDetail(row) {
      this.drawer = true;
      this.detailLoading = true;
      this.detail = null;
      this.logs = [];
      this.attachments = [];
      try {
        this.detail = await API.get('/work-orders/' + row.id);
        this.logs = await API.get('/work-orders/' + row.id + '/logs');
        this.loadAttachments();
      } catch (e) { ElMessage.error(e.message); this.drawer = false; }
      this.detailLoading = false;
    },
    pickAttach() { this.$refs.attachInput.value = ''; this.$refs.attachInput.click(); },
    fmtSize(n) { return fmtSize(n); },
    async onAttachPicked(ev) {
      const files = Array.from(ev.target.files || []);
      if (!files.length || !this.detail) return;
      for (const f of files) {
        if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
          ElMessage.error(f.name + '：' + (f.size / 1024 / 1024).toFixed(0) + 'MB 超过单文件上限 ' + MAX_UPLOAD_MB + 'MB');
          continue;
        }
        this.attachUploadName = f.name;
        this.attachUploadPct = 0;
        this.attachUploading = true;
        try {
          const fd = new FormData();
          fd.append('order_id', this.detail.id);
          fd.append('file', f);
          await API.upload('/files', fd, (pct) => { this.attachUploadPct = pct; });
          ElMessage.success('已上传附件：' + f.name);
        } catch (e) { ElMessage.error((f.name ? f.name + '：' : '') + e.message); }
        this.attachUploading = false;
      }
      this.loadAttachments();
    },
    async loadAttachments() {
      if (!this.detail) return;
      try {
        const fa = await API.get('/files?order_id=' + this.detail.id + '&page_size=100');
        this.attachments = fa.items;
      } catch (e) {}
    },
    async openAttach(a) {
      if (a.is_image) {
        try {
          this.previewUrl = await API.fetchObjectUrl('/files/' + a.id + '/content');
          this.previewName = a.name;
          this.previewRow = a;
          this.previewDlg = true;
        } catch (e) { ElMessage.error(e.message); }
      } else {
        this.downloadAttach(a);
      }
    },
    async downloadAttach(a) {
      try { await API.download('/files/' + a.id + '/download'); } catch (e) { ElMessage.error(e.message); }
    },
    canDeleteAttach(a) { return this.isManager || a.uploader_id === this.user.id; },
    async removeAttach(a) {
      try {
        await ElMessageBox.confirm(`确定删除附件「${a.name}」？`, '删除确认', { type: 'warning' });
      } catch (e) { return; }
      try {
        await API.del('/files/' + a.id);
        ElMessage.success('已删除');
        this.loadAttachments();
      } catch (e) { ElMessage.error(e.message); }
    },
    can(act) {
      if (!this.detail) return false;
      const u = this.user, o = this.detail;
      if (act === 'dispatch') return this.isManager && o.status === 'PENDING_DISPATCH';
      if (act === 'accept') return o.status === 'PENDING_ACCEPT' && o.assignee_id === u.id;
      if (act === 'complete') return o.status === 'PROCESSING' && o.assignee_id === u.id;
      if (act === 'verify') return this.isManager && o.status === 'PENDING_VERIFY';
      if (act === 'cancel') return o.status === 'PENDING_DISPATCH' || o.status === 'PENDING_ACCEPT';
      return false;
    },
    async loadDrafts() {
      try {
        const d = await API.get('/files?draft=1&page_size=100');
        this.draftFiles = d.items;
      } catch (e) {}
    },
    pickDraft() { this.$refs.draftInput.value = ''; this.$refs.draftInput.click(); },
    async onDraftPicked(ev) {
      const files = Array.from(ev.target.files || []);
      for (const f of files) {
        if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
          ElMessage.error(f.name + '：超过单文件上限 ' + MAX_UPLOAD_MB + 'MB');
          continue;
        }
        this.attachUploadName = f.name;
        this.attachUploadPct = 0;
        this.attachUploading = true;
        try {
          const fd = new FormData();
          fd.append('draft', '1');
          fd.append('file', f);
          await API.upload('/files', fd, (pct) => { this.attachUploadPct = pct; });
        } catch (e) { ElMessage.error(f.name + '：' + e.message); }
        this.attachUploading = false;
      }
      this.loadDrafts();
    },
    async downloadDraft(f) {
      try { await API.download('/files/' + f.id + '/download'); } catch (e) { ElMessage.error(e.message); }
    },
    async removeDraft(f) {
      try {
        await ElMessageBox.confirm('删除附件「' + f.name + '」？', '删除确认', { type: 'warning' });
      } catch (e) { return; }
      try {
        await API.del('/files/' + f.id);
        ElMessage.success('已删除');
        this.loadDrafts();
      } catch (e) { ElMessage.error(e.message); }
    },
    openCreate() {
      this.createForm = { title: '', order_type: this.isManager ? 'TASK' : 'FAULT', device_id: null, priority: 'P3', description: '', assignee_id: null };
      this.createDlg = true;
      if (this.isManager) this.loadDrafts();
    },
    async submitCreate() {
      if (!this.createForm.title.trim()) { ElMessage.warning('请填写工单标题'); return; }
      const body = { ...this.createForm, assignee_id: this.isManager ? this.createForm.assignee_id : null };
      if (this.isManager && this.draftFiles.length) body.draft_file_ids = this.draftFiles.map(f => f.id);
      this.creating = true;
      try {
        await API.post('/work-orders', body);
        ElMessage.success(this.isManager ? '工单创建成功' : '报修提交成功，等待调度派发');
        this.createDlg = false;
        if (this.isManager) this.draftFiles = [];
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.creating = false;
    },
    openDispatch() { this.dispatchForm.assignee_id = null; this.dispatchDlg = true; },
    async doDispatch() {
      if (!this.dispatchForm.assignee_id) { ElMessage.warning('请选择工程师'); return; }
      this.acting = true;
      try {
        await API.post('/work-orders/' + this.detail.id + '/dispatch', { assignee_id: this.dispatchForm.assignee_id });
        ElMessage.success('派单成功');
        this.dispatchDlg = false;
        this.closeAndReload();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    async doAccept() {
      this.acting = true;
      try {
        await API.post('/work-orders/' + this.detail.id + '/accept', {});
        ElMessage.success('接单成功，开始处理');
        this.closeAndReload();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    async loadCompleteDrafts() {
      try {
        const d = await API.get('/files?draft=1&page_size=100');
        this.completeFiles = d.items;
      } catch (e) {}
    },
    pickComplete() { this.$refs.completeInput.value = ''; this.$refs.completeInput.click(); },
    async onCompletePicked(ev) {
      const files = Array.from(ev.target.files || []);
      for (const f of files) {
        if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
          ElMessage.error(f.name + '：超过单文件上限 ' + MAX_UPLOAD_MB + 'MB');
          continue;
        }
        this.attachUploadName = f.name;
        this.attachUploadPct = 0;
        this.attachUploading = true;
        try {
          const fd = new FormData();
          fd.append('draft', '1');
          fd.append('file', f);
          await API.upload('/files', fd, (pct) => { this.attachUploadPct = pct; });
        } catch (e) { ElMessage.error(f.name + '：' + e.message); }
        this.attachUploading = false;
      }
      this.loadCompleteDrafts();
    },
    openComplete() { this.completeForm.result = ''; this.completeFiles = []; this.completeDlg = true; this.loadCompleteDrafts(); },
    async doComplete() {
      this.acting = true;
      try {
        const body = { result: this.completeForm.result };
        if (this.completeFiles.length) body.draft_file_ids = this.completeFiles.map(f => f.id);
        await API.post('/work-orders/' + this.detail.id + '/complete', body);
        ElMessage.success('已提交验收');
        this.completeDlg = false;
        this.completeFiles = [];
        this.closeAndReload();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    openVerify() { this.verifyForm = { passed: true, comment: '' }; this.verifyDlg = true; },
    async doVerify() {
      this.acting = true;
      try {
        await API.post('/work-orders/' + this.detail.id + '/verify', this.verifyForm);
        ElMessage.success(this.verifyForm.passed ? '验收通过' : '已驳回，退回处理');
        this.verifyDlg = false;
        this.closeAndReload();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    openCancel() { this.cancelForm.reason = ''; this.cancelDlg = true; },
    async doCancel() {
      this.acting = true;
      try {
        await API.post('/work-orders/' + this.detail.id + '/cancel', { reason: this.cancelForm.reason });
        ElMessage.success('工单已取消');
        this.cancelDlg = false;
        this.closeAndReload();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    closeAndReload() { this.drawer = false; this.detail = null; this.load(); },
  },
  mounted() { this.load(); this.loadDevices(); this.loadEngineers(); },
  watch: {
    tick() { this.load(); },
    openId: {
      handler(v) { if (v) { this.openDetailById(v); } },
      immediate: true,
    },
  },
};

/* ---------------- 设备台账 ---------------- */
const DevicesView = {
  name: 'DevicesView',
  props: ['user', 'tick'],
  template: `
    <div class="devices">
      <div class="toolbar">
        <div></div>
        <div class="toolbar-right">
          <el-button @click="load">刷新</el-button>
          <el-button v-if="user.role === 'ADMIN'" type="danger" plain @click="clearAllDevices">清空全部设备</el-button>
          <el-button v-if="isManager" type="primary" @click="openAdd">＋ 新增设备</el-button>
        </div>
      </div>
      <el-card shadow="never" class="panel">
        <el-table :data="list" v-loading="loading" stripe>
          <el-table-column prop="code" label="设备编号" width="100"></el-table-column>
          <el-table-column prop="name" label="设备名称" width="160" show-overflow-tooltip></el-table-column>
          <el-table-column prop="model" label="规格型号" width="110" show-overflow-tooltip></el-table-column>
          <el-table-column prop="manufacturer" label="制造商" width="110" show-overflow-tooltip></el-table-column>
          <el-table-column prop="location" label="安装位置" width="110"></el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="scope"><el-tag :type="DEVICE_STATUS_TAG[scope.row.status]" size="small">{{ scope.row.status_label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="保修状态" width="100">
            <template #default="scope">
              <el-tooltip :content="scope.row.warranty.expire ? '到期日 ' + scope.row.warranty.expire : ''">
                <el-tag size="small" :type="warrantyTag(scope.row)">{{ scope.row.warranty.status_label }}</el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="负责人" width="90">
            <template #default="scope">{{ scope.row.owner_name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip></el-table-column>
          <el-table-column v-if="isManager" label="操作" width="130" fixed="right">
            <template #default="scope">
              <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
              <el-button v-if="user.role === 'ADMIN'" link type="danger" @click="del(scope.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-dialog v-model="dlg" :title="editing ? '编辑设备' : '新增设备'" width="520px" :close-on-click-modal="false">
        <el-form label-width="100px">
          <el-form-item label="设备编号" required><el-input v-model="form.code" placeholder="与数字孪生设备编号一致，如 EQ-006"></el-input></el-form-item>
          <el-form-item label="设备名称" required><el-input v-model="form.name"></el-input></el-form-item>
          <el-form-item label="安装位置"><el-input v-model="form.location" placeholder="如：二号车间-1F"></el-input></el-form-item>
          <el-form-item label="孪生模型ID"><el-input v-model="form.twin_id" placeholder="数字孪生系统中的实体 ID"></el-input></el-form-item>
          <el-form-item label="规格型号"><el-input v-model="form.model" placeholder="如：VMC-850L"></el-input></el-form-item>
          <el-form-item label="制造商"><el-input v-model="form.manufacturer" placeholder="如：沈阳机床"></el-input></el-form-item>
          <el-form-item label="购置日期"><el-date-picker v-model="form.purchase_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width:100%"></el-date-picker></el-form-item>
          <el-form-item label="保修期"><el-input-number v-model="form.warranty_months" :min="0" :max="600"></el-input-number><span style="margin-left:8px">个月</span></el-form-item>
          <el-form-item label="状态"><el-select v-model="form.status" style="width:100%">
            <el-option label="运行" value="RUNNING"></el-option>
            <el-option label="告警" value="ALARM"></el-option>
            <el-option label="维修中" value="MAINTENANCE"></el-option>
            <el-option label="停机" value="OFFLINE"></el-option>
          </el-select></el-form-item>
          <el-form-item label="负责人"><el-select v-model="form.owner_id" clearable placeholder="选择工程师" style="width:100%">
            <el-option v-for="e in engineers" :key="e.id" :label="e.real_name + (e.title ? '（' + e.title + '）' : '')" :value="e.id"></el-option>
          </el-select></el-form-item>
          <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2"></el-input></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dlg = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </template>
      </el-dialog>
    </div>
  `,
  data() {
    return {
      list: [], loading: false,
      dlg: false, saving: false, editing: false, editingId: null,
      form: { code: '', name: '', location: '', twin_id: '', status: 'RUNNING', owner_id: null, description: '', model: '', manufacturer: '', purchase_date: null, warranty_months: null },
      engineers: [],
      DEVICE_STATUS_TAG,
    };
  },
  computed: {
    isManager() { return this.user.role === 'ADMIN' || this.user.role === 'DISPATCHER'; },
  },
  methods: {
    async load() {
      this.loading = true;
      try { this.list = await API.get('/devices'); } catch (e) { ElMessage.error(e.message); }
      this.loading = false;
    },
    async loadEngineers() {
      if (!this.isManager) return;
      try { this.engineers = await API.get('/users?role=ENGINEER'); } catch (e) {}
    },
    warrantyTag(row) {
      const m = { active: 'success', expiring: 'warning', expired: 'danger' };
      return m[row.warranty.status] || 'info';
    },
    async clearAllDevices() {
      try {
        await ElMessageBox.confirm(
          '将删除全部设备台账（共 ' + this.list.length + ' 台，含保养计划），删除后无法恢复，确定清空？',
          '管理员清空确认', { type: 'warning', confirmButtonText: '全部删除', cancelButtonText: '取消' }
        );
      } catch (e) { return; }
      try {
        const r = await API.del('/devices/all');
        ElMessage.success('已清空 ' + (r.deleted || 0) + ' 台设备（含保养计划 ' + (r.deleted_plans || 0) + ' 个）');
        this.load();
      } catch (e) { ElMessage.error(e.message); }
    },
    openAdd() { this.editing = false; this.editingId = null; this.form = { code: '', name: '', location: '', twin_id: '', status: 'RUNNING', owner_id: null, description: '', model: '', manufacturer: '', purchase_date: null, warranty_months: null }; this.dlg = true; },
    openEdit(row) {
      this.editing = true;
      this.editingId = row.id;
      this.form = { code: row.code, name: row.name, location: row.location, twin_id: row.twin_id, status: row.status, owner_id: row.owner_id, description: row.description, model: row.model, manufacturer: row.manufacturer, purchase_date: row.purchase_date, warranty_months: row.warranty_months };
      this.dlg = true;
    },
    async save() {
      if (!this.form.code.trim() || !this.form.name.trim()) { ElMessage.warning('请填写设备编号和名称'); return; }
      this.saving = true;
      try {
        if (this.editing) await API.put('/devices/' + this.editingId, this.form);
        else await API.post('/devices', this.form);
        ElMessage.success('保存成功');
        this.dlg = false;
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.saving = false;
    },
    async del(row) {
      try {
        await ElMessageBox.confirm('确定删除设备 ' + row.code + ' 吗？', '提示', { type: 'warning' });
      } catch (e) { return; }
      try {
        await API.del('/devices/' + row.id);
        ElMessage.success('已删除');
        this.load();
      } catch (e) { ElMessage.error(e.message); }
    },
  },
  mounted() { this.load(); this.loadEngineers(); },
};

/* ---------------- 报修管理（两段式） ---------------- */
const RR_STATUS_TAG = { PENDING_REVIEW: 'warning', APPROVED: 'success', REJECTED: 'danger', WITHDRAWN: 'info' };

const RepairsView = {
  name: 'RepairsView',
  props: ['user', 'tick'],
  template: `
    <div class="repairs">
      <div class="toolbar">
        <el-radio-group v-model="status" size="default" @change="onStatusChange">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="PENDING_REVIEW">待审核</el-radio-button>
          <el-radio-button label="APPROVED">已立项</el-radio-button>
          <el-radio-button label="REJECTED">已驳回</el-radio-button>
          <el-radio-button label="WITHDRAWN">已撤回</el-radio-button>
        </el-radio-group>
        <el-switch v-if="isManager" v-model="mine" active-text="只看我的报修" @change="onStatusChange" style="margin-left:16px"></el-switch>
        <div class="toolbar-right">
          <el-input v-model="keyword" placeholder="搜索标题 / 报修单号" clearable style="width:220px" @keyup.enter="search" @clear="search">
            <template #append><el-button @click="search">搜索</el-button></template>
          </el-input>
          <el-button @click="load">刷新</el-button>
          <el-button v-if="!isManager" type="primary" @click="openCreate">＋ 报修</el-button>
        </div>
      </div>

      <el-card shadow="never" class="panel">
        <el-table :data="list" v-loading="loading" stripe>
          <el-table-column prop="request_no" label="报修单号" width="150"></el-table-column>
          <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip></el-table-column>
          <el-table-column label="设备" width="150" show-overflow-tooltip>
            <template #default="scope">{{ scope.row.device_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="优先级" width="90">
            <template #default="scope"><el-tag :type="PRIORITY_TAG[scope.row.priority]" size="small">{{ scope.row.priority_label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="scope"><el-tag :type="RR_STATUS_TAG[scope.row.status]" size="small">{{ scope.row.status_label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="报修人" width="100">
            <template #default="scope">{{ scope.row.creator_name }}</template>
          </el-table-column>
          <el-table-column label="关联工单" width="150">
            <template #default="scope">{{ scope.row.work_order_no || '—' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="报修时间" width="150"></el-table-column>
          <el-table-column label="操作" width="190" fixed="right">
            <template #default="scope">
              <el-button v-if="isManager && scope.row.status === 'PENDING_REVIEW'" link type="primary" @click="openApprove(scope.row)">通过立项</el-button>
              <el-button v-if="isManager && scope.row.status === 'PENDING_REVIEW'" link type="danger" @click="openReject(scope.row)">驳回</el-button>
              <el-button v-if="!isManager && scope.row.status === 'PENDING_REVIEW' && scope.row.creator_id === user.id" link type="warning" @click="doWithdraw(scope.row)">撤回</el-button>
              <el-button link @click="openDetail(scope.row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination background layout="total, prev, pager, next" :total="total" :page-size="pageSize" :current-page="page" @current-change="onPage"></el-pagination>
        </div>
      </el-card>

      <!-- 报修 -->
      <el-dialog v-model="createDlg" title="故障报修" width="540px" :close-on-click-modal="false">
        <el-form label-width="90px">
          <el-form-item label="报修标题" required><el-input v-model="createForm.title" placeholder="如：一号车间输送带异响"></el-input></el-form-item>
          <el-form-item label="关联设备"><el-select v-model="createForm.device_id" clearable placeholder="选择设备" style="width:100%">
            <el-option v-for="d in devices" :key="d.id" :label="d.code + ' ' + d.name" :value="d.id"></el-option>
          </el-select></el-form-item>
          <el-form-item label="优先级"><el-select v-model="createForm.priority" style="width:100%">
            <el-option label="P1 紧急" value="P1"></el-option>
            <el-option label="P2 高" value="P2"></el-option>
            <el-option label="P3 中" value="P3"></el-option>
            <el-option label="P4 低" value="P4"></el-option>
          </el-select></el-form-item>
          <el-form-item label="故障描述"><el-input v-model="createForm.description" type="textarea" :rows="3" placeholder="描述故障现象"></el-input></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createDlg = false">取消</el-button>
          <el-button type="primary" :loading="acting" @click="submitCreate">提交报修</el-button>
        </template>
      </el-dialog>

      <!-- 审核立项 -->
      <el-dialog v-model="approveDlg" title="审核立项" width="540px" :close-on-click-modal="false">
        <div class="detail-head">
          <div class="detail-no">{{ approveTarget ? approveTarget.request_no : '' }}</div>
          <div class="detail-title">{{ approveTarget ? approveTarget.title : '' }}</div>
        </div>
        <el-form label-width="90px">
          <el-form-item label="工单类型"><el-select v-model="approveForm.order_type" style="width:100%">
            <el-option label="故障维修" value="FAULT"></el-option>
            <el-option label="巡检" value="INSPECTION"></el-option>
            <el-option label="保养" value="MAINTENANCE"></el-option>
            <el-option label="任务" value="TASK"></el-option>
          </el-select></el-form-item>
          <el-form-item label="优先级"><el-select v-model="approveForm.priority" style="width:100%">
            <el-option label="P1 紧急" value="P1"></el-option>
            <el-option label="P2 高" value="P2"></el-option>
            <el-option label="P3 中" value="P3"></el-option>
            <el-option label="P4 低" value="P4"></el-option>
          </el-select></el-form-item>
          <el-form-item label="指派工程师"><el-select v-model="approveForm.assignee_id" clearable placeholder="不选则立项后待派发" style="width:100%">
            <el-option v-for="e in engineers" :key="e.id" :label="e.real_name + '（' + (e.title || e.dept_name || '—') + '）'" :value="e.id"></el-option>
          </el-select></el-form-item>
          <el-form-item label="审核批注"><el-input v-model="approveForm.review_comment" type="textarea" :rows="2" placeholder="补充要求、注意事项等"></el-input></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="approveDlg = false">取消</el-button>
          <el-button type="primary" :loading="acting" @click="doApprove">通过立项</el-button>
        </template>
      </el-dialog>

      <!-- 驳回 -->
      <el-dialog v-model="rejectDlg" title="驳回报修单" width="480px">
        <el-input v-model="rejectForm.review_comment" type="textarea" :rows="3" placeholder="驳回原因"></el-input>
        <template #footer>
          <el-button @click="rejectDlg = false">取消</el-button>
          <el-button type="danger" :loading="acting" @click="doReject">确认驳回</el-button>
        </template>
      </el-dialog>

      <!-- 详情 -->
      <el-drawer v-model="drawer" size="520px">
        <template #header><span class="drawer-title">报修单详情</span></template>
        <div v-if="detail">
          <div class="detail-head">
            <div class="detail-no">{{ detail.request_no }}</div>
            <div class="detail-title">{{ detail.title }}</div>
            <el-tag :type="RR_STATUS_TAG[detail.status]" size="small">{{ detail.status_label }}</el-tag>
          </div>
          <el-descriptions :column="1" border size="small" class="desc">
            <el-descriptions-item label="关联设备">{{ detail.device_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="优先级">{{ detail.priority_label }}</el-descriptions-item>
            <el-descriptions-item label="报修人">{{ detail.creator_name }}</el-descriptions-item>
            <el-descriptions-item label="报修时间">{{ detail.created_at }}</el-descriptions-item>
            <el-descriptions-item v-if="detail.reviewer_name" label="审核人">{{ detail.reviewer_name }}（{{ detail.review_time }}）</el-descriptions-item>
            <el-descriptions-item v-if="detail.review_comment" label="审核批注">{{ detail.review_comment }}</el-descriptions-item>
            <el-descriptions-item label="关联工单">{{ detail.work_order_no || '—' }}</el-descriptions-item>
          </el-descriptions>
          <div class="block-title">报修描述</div>
          <div class="desc-text">{{ detail.description || '无' }}</div>
        </div>
      </el-drawer>
    </div>
  `,
  data() {
    return {
      list: [], total: 0, page: 1, pageSize: 10,
      status: '', mine: false, keyword: '', loading: false,
      devices: [], engineers: [],
      createDlg: false, createForm: { title: '', device_id: null, priority: 'P3', description: '' },
      approveDlg: false, approveTarget: null,
      approveForm: { order_type: 'FAULT', priority: 'P3', assignee_id: null, review_comment: '' },
      rejectDlg: false, rejectTarget: null, rejectForm: { review_comment: '' },
      drawer: false, detail: null,
      acting: false,
      RR_STATUS_TAG, PRIORITY_TAG,
    };
  },
  computed: {
    isManager() { return this.user.role === 'ADMIN' || this.user.role === 'DISPATCHER'; },
  },
  methods: {
    async load() {
      this.loading = true;
      try {
        const params = new URLSearchParams();
        if (this.status) params.set('status', this.status);
        if (this.mine) params.set('mine', '1');
        if (this.keyword) params.set('keyword', this.keyword);
        params.set('page', this.page);
        params.set('page_size', this.pageSize);
        const data = await API.get('/repair-requests?' + params.toString());
        this.list = data.items;
        this.total = data.total;
      } catch (e) { if (e.status !== 401) ElMessage.error(e.message); }
      this.loading = false;
    },
    onStatusChange() { this.page = 1; this.load(); },
    search() { this.page = 1; this.load(); },
    onPage(p) { this.page = p; this.load(); },
    async loadDevices() { try { this.devices = await API.get('/devices'); } catch (e) {} },
    async loadEngineers() {
      if (!this.isManager) return;
      try { this.engineers = await API.get('/users?role=ENGINEER'); } catch (e) {}
    },
    openCreate() {
      this.createForm = { title: '', device_id: null, priority: 'P3', description: '' };
      this.createDlg = true;
    },
    async submitCreate() {
      if (!this.createForm.title.trim()) { ElMessage.warning('请填写报修标题'); return; }
      this.acting = true;
      try {
        await API.post('/repair-requests', this.createForm);
        ElMessage.success('报修提交成功，等待调度审核');
        this.createDlg = false;
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    openApprove(row) {
      this.approveTarget = row;
      this.approveForm = { order_type: 'FAULT', priority: row.priority, assignee_id: null, review_comment: '' };
      this.approveDlg = true;
    },
    async doApprove() {
      this.acting = true;
      try {
        const res = await API.post('/repair-requests/' + this.approveTarget.id + '/approve', this.approveForm);
        ElMessage.success('立项成功，工单 ' + res.work_order.order_no + ' 已生成');
        this.approveDlg = false;
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    openReject(row) { this.rejectTarget = row; this.rejectForm.review_comment = ''; this.rejectDlg = true; },
    async doReject() {
      this.acting = true;
      try {
        await API.post('/repair-requests/' + this.rejectTarget.id + '/reject', this.rejectForm);
        ElMessage.success('报修单已驳回');
        this.rejectDlg = false;
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    async doWithdraw(row) {
      this.acting = true;
      try {
        await API.post('/repair-requests/' + row.id + '/withdraw', {});
        ElMessage.success('报修单已撤回');
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    openDetail(row) { this.detail = row; this.drawer = true; },
  },
  mounted() { this.load(); this.loadDevices(); this.loadEngineers(); },
  watch: { tick() { this.load(); } },
};

/* ---------------- 报表中心 ---------------- */
const ReportsView = {
  name: 'ReportsView',
  props: ['user', 'tick'],
  template: `
    <div class="reports">
      <div class="toolbar">
        <el-radio-group v-model="days" size="default" @change="load">
          <el-radio-button :label="7">近 7 天</el-radio-button>
          <el-radio-button :label="30">近 30 天</el-radio-button>
          <el-radio-button :label="90">近 90 天</el-radio-button>
        </el-radio-group>
        <div class="toolbar-right">
          <el-button @click="load">刷新</el-button>
          <el-button v-if="isManager" type="primary" @click="exportReport">导出 Excel 报表</el-button>
        </div>
      </div>

      <div class="kpi-row">
        <div class="kpi-card c1"><div class="kpi-label">工单总数</div><div class="kpi-value">{{ r.total }}<span class="kpi-unit">单</span></div></div>
        <div class="kpi-card c2"><div class="kpi-label">已完成</div><div class="kpi-value">{{ r.completed }}<span class="kpi-unit">单</span></div></div>
        <div class="kpi-card c3"><div class="kpi-label">完成率</div><div class="kpi-value">{{ r.completion_rate }}<span class="kpi-unit">%</span></div></div>
        <div class="kpi-card c5"><div class="kpi-label">平均处理时长</div><div class="kpi-value">{{ r.avg_hours }}<span class="kpi-unit">小时</span></div></div>
      </div>

      <el-row :gutter="16">
        <el-col :span="14">
          <el-card shadow="never" class="panel">
            <template #header><span class="panel-title">工单趋势（新增 / 完成）</span></template>
            <div ref="trendEl" class="chart"></div>
          </el-card>
        </el-col>
        <el-col :span="10">
          <el-card shadow="never" class="panel">
            <template #header><span class="panel-title">工单类型分布</span></template>
            <div ref="typeEl" class="chart"></div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16" class="chart-row">
        <el-col :span="12">
          <el-card shadow="never" class="panel">
            <template #header><span class="panel-title">设备故障排行 TOP10</span></template>
            <el-table :data="r.device_top" size="small" stripe>
              <el-table-column type="index" label="#" width="50"></el-table-column>
              <el-table-column prop="device" label="设备"></el-table-column>
              <el-table-column prop="count" label="故障工单数" width="100"></el-table-column>
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="never" class="panel">
            <template #header><span class="panel-title">工程师工作量</span></template>
            <el-table :data="r.engineer_ranking" size="small" stripe>
              <el-table-column prop="name" label="工程师" width="90"></el-table-column>
              <el-table-column prop="title" label="岗位" min-width="130"></el-table-column>
              <el-table-column prop="done" label="已完成" width="80"></el-table-column>
              <el-table-column prop="avg_hours" label="平均时长(h)" width="100"></el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>
    </div>
  `,
  data() {
    return {
      days: 7,
      r: { total: 0, completed: 0, completion_rate: 0, avg_hours: 0, device_top: [], engineer_ranking: [], trend: { labels: [], created: [], completed: [] }, type_distribution: [] },
      trendChart: null, typeChart: null,
    };
  },
  computed: {
    isManager() { return this.user.role === 'ADMIN' || this.user.role === 'DISPATCHER'; },
  },
  methods: {
    async load() {
      try { this.r = await API.get('/reports/summary?days=' + this.days); } catch (e) { ElMessage.error(e.message); }
      this.renderCharts();
    },
    renderCharts() {
      if (!this.$refs.trendEl || !this.$refs.typeEl) return;
      if (!this.trendChart) this.trendChart = echarts.init(this.$refs.trendEl);
      this.trendChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { bottom: 0 },
        grid: { left: 40, right: 20, top: 30, bottom: 40 },
        xAxis: { type: 'category', data: this.r.trend.labels },
        yAxis: { type: 'value', minInterval: 1 },
        series: [
          { name: '新增工单', type: 'line', smooth: true, data: this.r.trend.created, itemStyle: { color: '#409eff' }, areaStyle: { opacity: 0.15 } },
          { name: '完成工单', type: 'line', smooth: true, data: this.r.trend.completed, itemStyle: { color: '#67c23a' }, areaStyle: { opacity: 0.15 } },
        ],
      });
      if (!this.typeChart) this.typeChart = echarts.init(this.$refs.typeEl);
      this.typeChart.setOption({
        tooltip: { trigger: 'item' },
        legend: { bottom: 0 },
        color: ['#f56c6c', '#e6a23c', '#409eff', '#909399'],
        series: [{ type: 'pie', radius: ['40%', '65%'], center: ['50%', '44%'], label: { formatter: '{b}：{c}' }, data: this.r.type_distribution }],
      });
    },
    onResize() {
      if (this.trendChart) this.trendChart.resize();
      if (this.typeChart) this.typeChart.resize();
    },
    async exportReport() {
      try {
        await API.download('/reports/export?days=' + this.days);
        ElMessage.success('报表已导出');
      } catch (e) { ElMessage.error(e.message); }
    },
  },
  mounted() { this.load(); window.addEventListener('resize', this.onResize); },
  beforeUnmount() {
    window.removeEventListener('resize', this.onResize);
    if (this.trendChart) { this.trendChart.dispose(); this.trendChart = null; }
    if (this.typeChart) { this.typeChart.dispose(); this.typeChart = null; }
  },
};

/* ---------------- 公告通知 ---------------- */
const AnnounceView = {
  name: 'AnnounceView',
  props: ['user', 'tick'],
  template: `
    <div class="announce">
      <div class="toolbar">
        <div class="toolbar-hint">公司公告与通知</div>
        <div class="toolbar-right">
          <el-button @click="load">刷新</el-button>
          <el-button v-if="isManager" type="primary" @click="openPublish">＋ 发布公告</el-button>
        </div>
      </div>
      <el-card v-if="!list.length" shadow="never" class="panel">
        <div class="empty-tip">暂无公告</div>
      </el-card>
      <div v-for="a in list" :key="a.id" class="announce-item" @click="openDetail(a)">
        <div class="announce-left">
          <span class="unread-dot" :class="{ on: !a.read }"></span>
          <span class="announce-title">{{ a.title }}</span>
          <el-tag v-if="a.is_top" type="danger" size="small" effect="dark">置顶</el-tag>
          <el-tag v-if="!a.read" type="warning" size="small" effect="plain">未读</el-tag>
        </div>
        <div class="announce-meta">
          <span>{{ a.publisher_name }} · {{ a.created_at }}</span>
          <el-button v-if="user.role === 'ADMIN'" link type="danger" size="small" @click.stop="del(a)">删除</el-button>
        </div>
      </div>

      <el-dialog v-model="pubDlg" title="发布公告" width="540px" :close-on-click-modal="false">
        <el-form label-width="80px">
          <el-form-item label="标题" required><el-input v-model="pubForm.title"></el-input></el-form-item>
          <el-form-item label="内容"><el-input v-model="pubForm.content" type="textarea" :rows="5"></el-input></el-form-item>
          <el-form-item label="置顶"><el-switch v-model="pubForm.is_top"></el-switch></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="pubDlg = false">取消</el-button>
          <el-button type="primary" :loading="acting" @click="doPublish">发布</el-button>
        </template>
      </el-dialog>

      <el-drawer v-model="drawer" size="480px">
        <template #header><span class="drawer-title">公告详情</span></template>
        <div v-if="detail">
          <div class="detail-head">
            <div class="detail-title">{{ detail.title }}</div>
            <div class="detail-no">{{ detail.publisher_name }} · {{ detail.created_at }}</div>
          </div>
          <div class="desc-text" style="white-space:pre-wrap">{{ detail.content }}</div>
        </div>
      </el-drawer>
    </div>
  `,
  data() {
    return { list: [], pubDlg: false, pubForm: { title: '', content: '', is_top: false }, drawer: false, detail: null, acting: false };
  },
  computed: {
    isManager() { return this.user.role === 'ADMIN' || this.user.role === 'DISPATCHER'; },
  },
  methods: {
    async load() {
      try { this.list = await API.get('/announcements'); } catch (e) { ElMessage.error(e.message); }
      this.$emit('refresh-unread');
    },
    openPublish() { this.pubForm = { title: '', content: '', is_top: false }; this.pubDlg = true; },
    async doPublish() {
      if (!this.pubForm.title.trim()) { ElMessage.warning('请填写标题'); return; }
      this.acting = true;
      try {
        await API.post('/announcements', this.pubForm);
        ElMessage.success('公告已发布');
        this.pubDlg = false;
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    async openDetail(a) {
      this.drawer = true;
      try {
        this.detail = await API.get('/announcements/' + a.id);
        this.load();
      } catch (e) { ElMessage.error(e.message); }
    },
    async del(a) {
      try {
        await ElMessageBox.confirm('确定删除公告「' + a.title + '」吗？', '提示', { type: 'warning' });
      } catch (e) { return; }
      try {
        await API.del('/announcements/' + a.id);
        ElMessage.success('已删除');
        this.load();
      } catch (e) { ElMessage.error(e.message); }
    },
  },
  mounted() { this.load(); },
};

/* ---------------- 审批中心 ---------------- */
const AP_STATUS_TAG = { PENDING: 'warning', APPROVED: 'success', REJECTED: 'danger' };

const ApprovalsView = {
  name: 'ApprovalsView',
  props: ['user', 'tick'],
  template: `
    <div class="approvals">
      <div class="toolbar">
        <el-tabs v-model="tab" @tab-change="onTabChange" class="ap-tabs">
          <el-tab-pane label="我的申请" name="mine"></el-tab-pane>
          <el-tab-pane v-if="isManager" label="待我审批" name="todo"></el-tab-pane>
          <el-tab-pane v-if="isManager" label="全部审批" name="all"></el-tab-pane>
        </el-tabs>
        <div class="toolbar-right">
          <el-button @click="load">刷新</el-button>
          <el-button type="primary" @click="openCreate">＋ 新建申请</el-button>
        </div>
      </div>

      <el-card shadow="never" class="panel">
        <el-table :data="list" v-loading="loading" stripe>
          <el-table-column prop="no" label="单号" width="150"></el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="scope"><el-tag size="small" effect="plain">{{ scope.row.type_label }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip></el-table-column>
          <el-table-column label="申请人" width="110">
            <template #default="scope">{{ scope.row.applicant_name }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="scope"><el-tag size="small" :type="AP_STATUS_TAG[scope.row.status]">{{ scope.row.status_label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="当前环节" width="100">
            <template #default="scope">{{ scope.row.status === 'PENDING' ? (scope.row.steps[scope.row.current_step] || {}).role_label || '—' : '—' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="申请时间" width="150"></el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="scope">
              <el-button link @click="openDetail(scope.row)">详情</el-button>
              <el-button v-if="tab === 'todo'" link type="primary" @click="openAct(scope.row, true)">通过</el-button>
              <el-button v-if="tab === 'todo'" link type="danger" @click="openAct(scope.row, false)">驳回</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination background layout="total, prev, pager, next" :total="total" :page-size="pageSize" :current-page="page" @current-change="onPage"></el-pagination>
        </div>
      </el-card>

      <el-dialog v-model="createDlg" title="新建申请" width="520px" :close-on-click-modal="false">
        <el-form label-width="80px">
          <el-form-item label="申请类型"><el-select v-model="createForm.type" style="width:100%">
            <el-option label="请假申请" value="LEAVE"></el-option>
            <el-option label="领料申请" value="REQUISITION"></el-option>
            <el-option label="采购申请" value="PURCHASE"></el-option>
          </el-select></el-form-item>
          <el-form-item label="标题" required><el-input v-model="createForm.title" placeholder="如：请假一天（设备检修安排冲突）"></el-input></el-form-item>
          <el-form-item label="内容"><el-input v-model="createForm.content" type="textarea" :rows="4" placeholder="申请事由与明细"></el-input></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createDlg = false">取消</el-button>
          <el-button type="primary" :loading="acting" @click="submitCreate">提交申请</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="actDlg" :title="actApprove ? '审批通过' : '驳 回'" width="480px">
        <el-input v-model="actForm.comment" type="textarea" :rows="3" :placeholder="actApprove ? '审批意见' : '驳回原因'"></el-input>
        <template #footer>
          <el-button @click="actDlg = false">取消</el-button>
          <el-button :type="actApprove ? 'primary' : 'danger'" :loading="acting" @click="doAct">{{ actApprove ? '确认通过' : '确认驳回' }}</el-button>
        </template>
      </el-dialog>

      <el-drawer v-model="drawer" size="480px">
        <template #header><span class="drawer-title">审批单详情</span></template>
        <div v-if="detail">
          <div class="detail-head">
            <div class="detail-no">{{ detail.no }}</div>
            <div class="detail-title">{{ detail.title }}</div>
            <el-tag :type="AP_STATUS_TAG[detail.status]" size="small">{{ detail.status_label }}</el-tag>
          </div>
          <el-descriptions :column="1" border size="small" class="desc">
            <el-descriptions-item label="类型">{{ detail.type_label }}</el-descriptions-item>
            <el-descriptions-item label="申请人">{{ detail.applicant_name }}<span v-if="detail.applicant_title">（{{ detail.applicant_title }}）</span></el-descriptions-item>
            <el-descriptions-item label="申请时间">{{ detail.created_at }}</el-descriptions-item>
          </el-descriptions>
          <div class="block-title">申请内容</div>
          <div class="desc-text" style="white-space:pre-wrap">{{ detail.content || '无' }}</div>
          <div class="block-title">审批流程</div>
          <el-timeline>
            <el-timeline-item v-for="s in detail.steps" :key="s.step_index"
              :type="s.status === 'APPROVED' ? 'success' : s.status === 'REJECTED' ? 'danger' : ''"
              :timestamp="s.acted_at || '待审批'">
              {{ s.role_label }}审批 <b v-if="s.approver_name">{{ s.approver_name }}</b>
              <span v-if="s.comment"> — {{ s.comment }}</span>
            </el-timeline-item>
          </el-timeline>
        </div>
      </el-drawer>
    </div>
  `,
  data() {
    return {
      tab: 'mine', list: [], total: 0, page: 1, pageSize: 10, loading: false,
      createDlg: false, createForm: { type: 'LEAVE', title: '', content: '' },
      actDlg: false, actTarget: null, actApprove: true, actForm: { comment: '' },
      drawer: false, detail: null, acting: false,
      AP_STATUS_TAG,
    };
  },
  computed: {
    isManager() { return this.user.role === 'ADMIN' || this.user.role === 'DISPATCHER'; },
  },
  methods: {
    async load() {
      this.loading = true;
      try {
        const params = new URLSearchParams({ tab: this.tab, page: this.page, page_size: this.pageSize });
        const data = await API.get('/approvals?' + params.toString());
        this.list = data.items;
        this.total = data.total;
      } catch (e) { ElMessage.error(e.message); }
      this.loading = false;
    },
    onTabChange() { this.page = 1; this.load(); },
    onPage(p) { this.page = p; this.load(); },
    openCreate() { this.createForm = { type: 'LEAVE', title: '', content: '' }; this.createDlg = true; },
    async submitCreate() {
      if (!this.createForm.title.trim()) { ElMessage.warning('请填写标题'); return; }
      this.acting = true;
      try {
        await API.post('/approvals', this.createForm);
        ElMessage.success('申请已提交');
        this.createDlg = false;
        this.tab = 'mine';
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    openAct(row, approve) { this.actTarget = row; this.actApprove = approve; this.actForm.comment = ''; this.actDlg = true; },
    async doAct() {
      this.acting = true;
      try {
        await API.post('/approvals/' + this.actTarget.id + (this.actApprove ? '/approve' : '/reject'), this.actForm);
        ElMessage.success(this.actApprove ? '已通过' : '已驳回');
        this.actDlg = false;
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.acting = false;
    },
    async openDetail(row) {
      this.drawer = true;
      try { this.detail = await API.get('/approvals/' + row.id); } catch (e) { ElMessage.error(e.message); }
    },
  },
  mounted() { this.load(); },
};

/* ---------------- 保养计划 ---------------- */
const PlansView = {
  name: 'PlansView',
  props: ['user', 'tick'],
  template: `
    <div class="plans">
      <div class="toolbar">
        <div class="toolbar-hint">到期保养计划将自动生成保养工单</div>
        <div class="toolbar-right">
          <el-button @click="load">刷新</el-button>
          <el-button v-if="isManager" type="primary" @click="openAdd">＋ 新建保养计划</el-button>
        </div>
      </div>
      <el-card shadow="never" class="panel">
        <el-table :data="list" v-loading="loading" stripe>
          <el-table-column prop="name" label="计划名称" min-width="200" show-overflow-tooltip></el-table-column>
          <el-table-column label="设备" width="160" show-overflow-tooltip>
            <template #default="scope">{{ scope.row.device_name }}</template>
          </el-table-column>
          <el-table-column label="周期" width="80">
            <template #default="scope">{{ scope.row.cycle_days }} 天</template>
          </el-table-column>
          <el-table-column label="下次执行" width="150">
            <template #default="scope">
              <span :class="{ 'due-now': scope.row.enabled && scope.row.next_due_date && scope.row.next_due_date <= today }">{{ scope.row.next_due_date || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="上次执行" width="150">
            <template #default="scope">{{ scope.row.last_run_date || '—' }}</template>
          </el-table-column>
          <el-table-column label="负责人" width="90">
            <template #default="scope">{{ scope.row.owner_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="scope"><el-tag size="small" :type="scope.row.enabled ? 'success' : 'info'">{{ scope.row.enabled ? '启用' : '停用' }}</el-tag></template>
          </el-table-column>
          <el-table-column label="进行中工单" width="140">
            <template #default="scope">{{ scope.row.active_work_order_no || '—' }}</template>
          </el-table-column>
          <el-table-column v-if="isManager" label="操作" width="190" fixed="right">
            <template #default="scope">
              <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
              <el-button link type="success" @click="runNow(scope.row)">立即生成</el-button>
              <el-button v-if="user.role === 'ADMIN'" link type="danger" @click="del(scope.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-dialog v-model="dlg" :title="editing ? '编辑保养计划' : '新建保养计划'" width="540px" :close-on-click-modal="false">
        <el-form label-width="90px">
          <el-form-item label="计划名称" required><el-input v-model="form.name" placeholder="如：数控机床月度保养"></el-input></el-form-item>
          <el-form-item label="设备" required><el-select v-model="form.device_id" style="width:100%">
            <el-option v-for="d in devices" :key="d.id" :label="d.code + ' ' + d.name" :value="d.id"></el-option>
          </el-select></el-form-item>
          <el-form-item label="保养周期"><el-input-number v-model="form.cycle_days" :min="1" :max="3650"></el-input-number><span style="margin-left:8px">天</span></el-form-item>
          <el-form-item label="下次执行"><el-date-picker v-model="form.next_due_date" type="date" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="选择日期" style="width:100%"></el-date-picker></el-form-item>
          <el-form-item label="负责人"><el-select v-model="form.owner_id" clearable placeholder="选择工程师" style="width:100%">
            <el-option v-for="e in engineers" :key="e.id" :label="e.real_name + (e.title ? '（' + e.title + '）' : '')" :value="e.id"></el-option>
          </el-select></el-form-item>
          <el-form-item label="启用"><el-switch v-model="form.enabled"></el-switch></el-form-item>
          <el-form-item label="保养内容"><el-input v-model="form.description" type="textarea" :rows="2"></el-input></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dlg = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </template>
      </el-dialog>
    </div>
  `,
  data() {
    return {
      list: [], loading: false, devices: [], engineers: [],
      dlg: false, saving: false, editing: false, editingId: null,
      form: { name: '', device_id: null, cycle_days: 30, next_due_date: null, owner_id: null, enabled: true, description: '' },
      today: new Date().toISOString().slice(0, 10),
    };
  },
  computed: {
    isManager() { return this.user.role === 'ADMIN' || this.user.role === 'DISPATCHER'; },
  },
  methods: {
    async load() {
      this.loading = true;
      try { this.list = await API.get('/maintenance-plans'); } catch (e) { ElMessage.error(e.message); }
      this.loading = false;
    },
    async loadDevices() { try { this.devices = await API.get('/devices'); } catch (e) {} },
    async loadEngineers() {
      if (!this.isManager) return;
      try { this.engineers = await API.get('/users?role=ENGINEER'); } catch (e) {}
    },
    openAdd() {
      this.editing = false;
      this.editingId = null;
      this.form = { name: '', device_id: null, cycle_days: 30, next_due_date: null, owner_id: null, enabled: true, description: '' };
      this.dlg = true;
    },
    openEdit(row) {
      this.editing = true;
      this.editingId = row.id;
      this.form = { name: row.name, device_id: row.device_id, cycle_days: row.cycle_days, next_due_date: row.next_due_date, owner_id: row.owner_id, enabled: row.enabled, description: row.description };
      this.dlg = true;
    },
    async save() {
      if (!this.form.name.trim() || !this.form.device_id) { ElMessage.warning('请填写计划名称并选择设备'); return; }
      this.saving = true;
      try {
        if (this.editing) await API.put('/maintenance-plans/' + this.editingId, this.form);
        else await API.post('/maintenance-plans', this.form);
        ElMessage.success('保存成功');
        this.dlg = false;
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.saving = false;
    },
    async runNow(row) {
      try {
        const res = await API.post('/maintenance-plans/' + row.id + '/run-now', {});
        ElMessage.success('已生成保养工单 ' + res.work_order);
        this.load();
      } catch (e) { ElMessage.error(e.message); }
    },
    async del(row) {
      try {
        await ElMessageBox.confirm('确定删除保养计划「' + row.name + '」吗？', '提示', { type: 'warning' });
      } catch (e) { return; }
      try {
        await API.del('/maintenance-plans/' + row.id);
        ElMessage.success('已删除');
        this.load();
      } catch (e) { ElMessage.error(e.message); }
    },
  },
  mounted() { this.load(); this.loadDevices(); this.loadEngineers(); },
};

/* ---------------- 权限管理 ---------------- */
const AdminView = {
  name: 'AdminView',
  props: ['user', 'tick'],
  template: `
    <div class="admin">
      <el-tabs v-model="tab" class="admin-tabs">
        <el-tab-pane label="用户权限" name="users">
      <div class="toolbar">
        <div class="toolbar-hint">管理员可在此划分每位用户的功能模块权限</div>
        <div class="toolbar-right">
          <el-button @click="load">刷新</el-button>
          <el-button type="primary" @click="openCreate">＋ 新增用户</el-button>
        </div>
      </div>
      <el-card shadow="never" class="panel">
        <el-table :data="list" v-loading="loading" stripe>
          <el-table-column prop="username" label="账号" width="120"></el-table-column>
          <el-table-column prop="real_name" label="姓名" width="100"></el-table-column>
          <el-table-column prop="title" label="岗位" width="160" show-overflow-tooltip></el-table-column>
          <el-table-column label="角色" width="90">
            <template #default="scope"><el-tag size="small" :type="roleTag(scope.row.role)">{{ scope.row.role_label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="模块权限" min-width="240">
            <template #default="scope">
              <el-tag v-for="m in scope.row.permissions" :key="m" size="small" effect="plain" class="perm-tag">{{ moduleLabel(m) }}</el-tag>
              <span v-if="!scope.row.permissions.length" class="no-perm">无任何模块权限</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="scope"><el-tag size="small" :type="scope.row.enabled ? 'success' : 'info'">{{ scope.row.enabled ? '启用' : '禁用' }}</el-tag></template>
          </el-table-column>
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="scope">
              <el-button link type="primary" @click="openEdit(scope.row)">编辑权限</el-button>
              <el-button link type="warning" @click="openReset(scope.row)">重置密码</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
        </el-tab-pane>
        <el-tab-pane label="审计日志" name="audit">
          <div class="toolbar">
            <div class="toolbar-hint">系统关键操作记录（登录、权限、设备、工单、审批等）</div>
            <div class="toolbar-right">
              <el-button @click="loadAudit">刷新</el-button>
            </div>
          </div>
          <el-card shadow="never" class="panel">
            <el-table :data="auditList" v-loading="auditLoading" stripe>
              <el-table-column prop="created_at" label="时间" width="160"></el-table-column>
              <el-table-column prop="username" label="用户" width="100"></el-table-column>
              <el-table-column label="操作" width="160">
                <template #default="scope"><el-tag size="small" :type="actionTag(scope.row.action)">{{ scope.row.action }}</el-tag></template>
              </el-table-column>
              <el-table-column prop="detail" label="详情" min-width="280" show-overflow-tooltip></el-table-column>
              <el-table-column prop="ip" label="IP" width="120"></el-table-column>
            </el-table>
            <div class="pager">
              <el-pagination background layout="total, prev, pager, next" :total="auditTotal" :page-size="20" :current-page="auditPage" @current-change="onAuditPage"></el-pagination>
            </div>
          </el-card>
        </el-tab-pane>
      </el-tabs>

      <el-dialog v-model="editDlg" title="编辑用户与权限" width="520px" :close-on-click-modal="false">
        <el-form label-width="90px">
          <el-form-item label="账号"><el-input v-model="form.username" disabled></el-input></el-form-item>
          <el-form-item label="姓名"><el-input v-model="form.real_name"></el-input></el-form-item>
          <el-form-item label="岗位"><el-input v-model="form.title"></el-input></el-form-item>
          <el-form-item label="角色"><el-select v-model="form.role" :disabled="isSelf" style="width:100%" @change="onRoleChange">
            <el-option label="工程师" value="ENGINEER"></el-option>
            <el-option label="调度员" value="DISPATCHER"></el-option>
            <el-option label="管理员" value="ADMIN"></el-option>
          </el-select></el-form-item>
          <el-form-item label="模块权限"><el-checkbox-group v-model="form.permissions" :disabled="isSelf || form.role === 'ADMIN'">
            <el-checkbox v-for="m in moduleOptions" :key="m.key" :value="m.key">{{ m.label }}</el-checkbox>
          </el-checkbox-group></el-form-item>
          <el-form-item label="账号状态"><el-switch v-model="form.enabled" :disabled="isSelf" active-text="启用" inactive-text="禁用"></el-switch></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editDlg = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="createDlg" title="新增用户" width="520px" :close-on-click-modal="false">
        <el-form label-width="90px">
          <el-form-item label="账号" required><el-input v-model="createForm.username"></el-input></el-form-item>
          <el-form-item label="密码" required><el-input v-model="createForm.password" show-password></el-input></el-form-item>
          <el-form-item label="姓名" required><el-input v-model="createForm.real_name"></el-input></el-form-item>
          <el-form-item label="岗位"><el-input v-model="createForm.title"></el-input></el-form-item>
          <el-form-item label="角色"><el-select v-model="createForm.role" style="width:100%" @change="onCreateRoleChange">
            <el-option label="工程师" value="ENGINEER"></el-option>
            <el-option label="调度员" value="DISPATCHER"></el-option>
            <el-option label="管理员" value="ADMIN"></el-option>
          </el-select></el-form-item>
          <el-form-item label="模块权限"><el-checkbox-group v-model="createForm.permissions" :disabled="createForm.role === 'ADMIN'">
            <el-checkbox v-for="m in moduleOptions" :key="m.key" :value="m.key">{{ m.label }}</el-checkbox>
          </el-checkbox-group></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createDlg = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveCreate">创建</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="resetDlg" title="重置密码" width="420px">
        <el-form label-width="90px">
          <el-form-item label="用户">{{ resetTarget ? resetTarget.real_name + '（' + resetTarget.username + '）' : '' }}</el-form-item>
          <el-form-item label="新密码" required><el-input v-model="resetForm.new_password" show-password placeholder="至少 6 位"></el-input></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="resetDlg = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="doReset">确认重置</el-button>
        </template>
      </el-dialog>
    </div>
  `,
  data() {
    return {
      list: [], loading: false,
      tab: 'users',
      auditList: [], auditTotal: 0, auditPage: 1, auditLoading: false,
      editDlg: false, createDlg: false, resetDlg: false, saving: false,
      editingId: null,
      form: { username: '', real_name: '', title: '', role: 'ENGINEER', permissions: [], enabled: true },
      createForm: { username: '', password: '', real_name: '', title: '', role: 'ENGINEER', permissions: ['dashboard', 'orders', 'repairs', 'reports', 'devices', 'plans', 'announce', 'approvals'] },
      resetTarget: null, resetForm: { new_password: '' },
      moduleOptions: [
        { key: 'dashboard', label: '工作台' },
        { key: 'orders', label: '工单管理' },
        { key: 'repairs', label: '报修管理' },
        { key: 'reports', label: '报表中心' },
        { key: 'devices', label: '设备台账' },
        { key: 'plans', label: '保养计划' },
        { key: 'announce', label: '公告通知' },
        { key: 'approvals', label: '审批中心' },
        { key: 'files', label: '文件共享' },
        { key: 'twin', label: '孪生对接' },
        { key: 'track', label: '工单跟踪（收到接单/完成等反馈提醒）' },
        { key: 'admin', label: '权限管理' },
      ],
    };
  },
  computed: {
    isSelf() { return this.user && this.editingId === this.user.id; },
  },
  methods: {
    moduleLabel(key) {
      const m = this.moduleOptions.find(function (x) { return x.key === key; });
      return m ? m.label : key;
    },
    roleTag(role) {
      return role === 'ADMIN' ? 'danger' : role === 'DISPATCHER' ? 'warning' : 'primary';
    },
    actionTag(action) {
      if (action.includes('LOGIN')) return action === 'LOGIN_SUCCESS' ? 'success' : 'warning';
      if (action.includes('DELETE') || action.includes('REJECT') || action.includes('CANCEL')) return 'danger';
      if (action.includes('CREATE') || action.includes('APPROVE') || action.includes('VERIFY') || action.includes('PUBLISH') || action.includes('RESET')) return 'primary';
      return 'info';
    },
    async loadAudit() {
      this.auditLoading = true;
      try {
        const d = await API.get('/audit-logs?page=' + this.auditPage + '&page_size=20');
        this.auditList = d.items;
        this.auditTotal = d.total;
      } catch (e) { ElMessage.error(e.message); }
      this.auditLoading = false;
    },
    onAuditPage(p) { this.auditPage = p; this.loadAudit(); },
    async load() {
      this.loading = true;
      try { this.list = await API.get('/users'); } catch (e) { ElMessage.error(e.message); }
      this.loading = false;
    },
    openEdit(row) {
      this.editingId = row.id;
      this.form = {
        username: row.username,
        real_name: row.real_name,
        title: row.title || '',
        role: row.role,
        permissions: [...(row.permissions || [])],
        enabled: row.enabled,
      };
      this.editDlg = true;
    },
    onRoleChange() {
      if (this.form.role === 'ADMIN') this.form.permissions = this.moduleOptions.map(function (m) { return m.key; });
      else this.form.permissions = this.form.permissions.filter(function (m) { return m !== 'admin'; });
    },
    async saveEdit() {
      this.saving = true;
      try {
        await API.put('/users/' + this.editingId, {
          real_name: this.form.real_name,
          title: this.form.title,
          role: this.form.role,
          enabled: this.form.enabled,
          permissions: this.form.permissions,
        });
        ElMessage.success('权限保存成功');
        this.editDlg = false;
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.saving = false;
    },
    openCreate() {
      this.createForm = { username: '', password: '', real_name: '', title: '', role: 'ENGINEER', permissions: ['dashboard', 'orders', 'repairs', 'reports', 'devices', 'plans', 'announce', 'approvals'] };
      this.createDlg = true;
    },
    onCreateRoleChange() {
      if (this.createForm.role === 'ADMIN') this.createForm.permissions = this.moduleOptions.map(function (m) { return m.key; });
      else this.createForm.permissions = this.createForm.permissions.filter(function (m) { return m !== 'admin'; });
    },
    async saveCreate() {
      if (!this.createForm.username || !this.createForm.password || !this.createForm.real_name) {
        ElMessage.warning('请填写账号、密码和姓名');
        return;
      }
      this.saving = true;
      try {
        await API.post('/users', this.createForm);
        ElMessage.success('用户创建成功');
        this.createDlg = false;
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.saving = false;
    },
    openReset(row) { this.resetTarget = row; this.resetForm.new_password = ''; this.resetDlg = true; },
    async doReset() {
      if (this.resetForm.new_password.length < 6) { ElMessage.warning('密码至少 6 位'); return; }
      this.saving = true;
      try {
        await API.put('/users/' + this.resetTarget.id + '/reset-password', { new_password: this.resetForm.new_password });
        ElMessage.success('密码已重置');
        this.resetDlg = false;
      } catch (e) { ElMessage.error(e.message); }
      this.saving = false;
    },
  },
  mounted() { this.load(); this.loadAudit(); },
};

/* ---------------- 文件共享 ---------------- */
const FilesView = {
  name: 'FilesView',
  props: ['user', 'tick'],
  template: `
    <div class="files">
      <div class="toolbar">
        <div>
          <el-button type="primary" @click="pickFiles">⬆ 上传文件（可多选）</el-button>
          <input ref="fileInput" type="file" multiple style="display:none" @change="onFilesPicked">
          <span class="no-perm" style="margin-left:12px">同公司员工可通过这里互传工作文件与文档（单文件 ≤ 500MB）</span>
        </div>
        <div class="toolbar-right">
          <el-button v-if="isAdmin" type="danger" plain @click="clearAllFiles">清空全部文件</el-button>
          <el-button @click="load">刷新</el-button>
        </div>
      </div>

      <el-card v-if="uploading || uploadResult" shadow="never" class="panel upload-card">
        <div class="up-head">
          <b>{{ uploading ? '正在上传 ' + uploadIdx + ' / ' + uploadTotal : '上传完成' }}</b>
          <span class="up-name">{{ uploadName }}</span>
        </div>
        <el-progress :percentage="uploadPct" :stroke-width="16" :text-inside="true" striped striped-flow></el-progress>
        <div v-if="uploadResult" class="up-result">{{ uploadResult }}</div>
      </el-card>

      <el-card shadow="never" class="panel">
        <div class="file-grid">
          <div class="file-row file-head">
            <div class="f-name">文件名</div>
            <div class="f-size">大小</div>
            <div class="f-uploader">上传人</div>
            <div class="f-time">上传时间</div>
            <div class="f-ops">操作</div>
          </div>
          <div v-for="(row, i) in list" :key="row.id" class="file-row" :class="{ odd: i % 2 === 1 }">
            <div class="f-name"><a class="link" @click="openFile(row)"><span class="ft-ico" :class="row.is_image ? 'img' : 'doc'">{{ row.is_image ? '图' : '文' }}</span>{{ row.name }}</a></div>
            <div class="f-size">{{ fmtSize(row.size) }}</div>
            <div class="f-uploader">{{ row.uploader_name }}</div>
            <div class="f-time">{{ row.created_at }}</div>
            <div class="f-ops">
              <el-button link type="primary" @click="download(row)">下载</el-button>
              <el-button v-if="canDelete(row)" link type="danger" @click="remove(row)">删除</el-button>
            </div>
          </div>
        </div>
        <div v-if="!loading && !list.length" class="empty-tip">暂无共享文件，点击「上传文件」即可向全公司分享工作文档</div>
        <div class="pager">
          <el-pagination background layout="total, prev, pager, next" :total="total" :page-size="pageSize" :current-page="page" @current-change="onPage"></el-pagination>
        </div>
      </el-card>

      <!-- 图片预览 -->
      <el-dialog v-model="previewDlg" :title="previewName" width="720px" :close-on-click-modal="false">
        <div style="text-align:center"><img :src="previewUrl" style="max-width:100%;max-height:70vh"></div>
        <template #footer>
          <el-button @click="previewDlg = false">关闭</el-button>
          <el-button type="primary" @click="download(previewRow)">下载</el-button>
        </template>
      </el-dialog>
    </div>
  `,
  data() {
    return {
      list: [], total: 0, page: 1, pageSize: 20, loading: false,
      previewDlg: false, previewUrl: '', previewName: '', previewRow: null,
      uploading: false, uploadIdx: 0, uploadTotal: 0, uploadName: '', uploadPct: 0, uploadResult: '',
    };
  },
  computed: {
    isAdmin() { return this.user.role === 'ADMIN'; },
  },
  methods: {
    fmtSize(n) { return fmtSize(n); },
    canDelete(row) { return this.isAdmin || row.uploader_id === this.user.id; },
    async load() {
      this.loading = true;
      try {
        const data = await API.get('/files?page=' + this.page + '&page_size=' + this.pageSize);
        this.list = data.items;
        this.total = data.total;
      } catch (e) { if (e.status !== 401) ElMessage.error(e.message); }
      this.loading = false;
    },
    onPage(p) { this.page = p; this.load(); },
    pickFiles() { this.$refs.fileInput.value = ''; this.$refs.fileInput.click(); },
    async onFilesPicked(ev) {
      const files = Array.from(ev.target.files || []);
      if (!files.length) return;
      this.uploadTotal = files.length;
      this.uploadIdx = 0;
      this.uploadResult = '';
      const errors = [];
      for (const f of files) {
        if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
          errors.push(f.name + '：' + (f.size / 1024 / 1024).toFixed(0) + 'MB 超过上限 ' + MAX_UPLOAD_MB + 'MB');
          continue;
        }
        this.uploadIdx += 1;
        this.uploadName = f.name;
        this.uploadPct = 0;
        this.uploading = true;
        try {
          const fd = new FormData();
          fd.append('file', f);
          await API.upload('/files', fd, (pct) => { this.uploadPct = pct; });
        } catch (e) { errors.push(f.name + '：' + e.message); }
      }
      this.uploading = false;
      this.uploadPct = 100;
      const okCount = this.uploadTotal - errors.length;
      this.uploadResult = '成功 ' + okCount + ' 个' + (errors.length ? '，失败 ' + errors.length + ' 个：' + errors.join('；') : '');
      setTimeout(() => { this.uploadResult = ''; }, 12000);
      this.load();
    },
    async openFile(row) {
      if (row.is_image) {
        try {
          this.previewUrl = await API.fetchObjectUrl('/files/' + row.id + '/content');
          this.previewName = row.name;
          this.previewRow = row;
          this.previewDlg = true;
        } catch (e) { ElMessage.error(e.message); }
      } else {
        this.download(row);
      }
    },
    async download(row) {
      try { await API.download('/files/' + row.id + '/download'); } catch (e) { ElMessage.error(e.message); }
    },
    async clearAllFiles() {
      try {
        await ElMessageBox.confirm(
          '将删除服务器上全部共享文件与工单附件（共 ' + this.total + ' 个），删除后无法恢复，确定清空？',
          '管理员清空确认', { type: 'warning', confirmButtonText: '全部删除', cancelButtonText: '取消' }
        );
      } catch (e) { return; }
      try {
        const r = await API.del('/files/all');
        ElMessage.success('已清空 ' + (r.deleted || 0) + ' 个文件');
        this.load();
      } catch (e) { ElMessage.error(e.message); }
    },
    async remove(row) {
      try {
        await ElMessageBox.confirm(`确定删除文件「${row.name}」？删除后无法恢复。`, '删除确认', { type: 'warning' });
      } catch (e) { return; }
      try {
        await API.del('/files/' + row.id);
        ElMessage.success('已删除');
        this.load();
      } catch (e) { ElMessage.error(e.message); }
    },
  },
  mounted() { this.load(); },
  watch: { tick() { this.load(); } },
};

/* ---------------- 孪生对接 ---------------- */
const TwinView = {
  name: 'TwinView',
  props: ['user', 'tick'],
  template: `
    <div class="twin">
      <el-row :gutter="16" style="margin-bottom:16px">
        <el-col :span="12">
          <el-card shadow="never" class="panel">
            <template #header><span class="panel-title">对接状态</span></template>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="回调地址">
                <span v-if="ov.callback_url">{{ ov.callback_url }}</span>
                <span v-else style="color:#e6a23c">未配置（工单状态变更不会推送给孪生）</span>
              </el-descriptions-item>
              <el-descriptions-item label="鉴权方式">
                <span style="color:#67c23a">局域网免鉴权（白名单模式）</span>
              </el-descriptions-item>
              <el-descriptions-item label="孪生最近调用">{{ ov.last_in_at ? (ov.last_in_at + ' · ' + ov.last_in_action) : '暂无' }}</el-descriptions-item>
              <el-descriptions-item label="最近成功回调">{{ ov.last_out_at || '暂无' }}</el-descriptions-item>
            </el-descriptions>
            <div style="margin-top:14px;display:flex;gap:10px">
              <el-button @click="load">刷新</el-button>
              <el-button type="primary" plain @click="doTestCallback" :loading="testing">测试回调连通性</el-button>
            </div>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="never" class="panel">
            <template #header><span class="panel-title">OA 工单总览（孪生可同步的数据）</span></template>
            <div class="twin-stat-grid">
              <div class="twin-stat"><div class="twin-stat-num">{{ ov.total_orders }}</div><div class="twin-stat-label">工单总数</div></div>
              <div class="twin-stat"><div class="twin-stat-num">{{ ov.created_today }}</div><div class="twin-stat-label">今日新增</div></div>
              <div v-for="s in ov.status_counts || []" :key="s.status" class="twin-stat">
                <div class="twin-stat-num">{{ s.count }}</div>
                <div class="twin-stat-label">{{ s.label }}</div>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <el-card shadow="never" class="panel" v-if="isAdmin">
        <template #header><span class="panel-title">对接配置（保存后立即生效，无需重启服务）</span></template>
        <el-form label-width="110px" style="max-width:640px" @submit.prevent>
          <el-form-item label="孪生回调地址">
            <el-input v-model="cfgForm.callback_url" placeholder="如 http://192.168.1.50:9000/api/oa/callback，留空则不回调"></el-input>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" @click="saveCfg">保存配置</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <el-card shadow="never" class="panel">
        <template #header><span class="panel-title">对接日志（最近 50 条）</span></template>
        <div class="file-grid">
          <div class="file-row file-head">
            <div class="f-time">时间</div>
            <div class="f-dir">方向</div>
            <div class="f-action">动作</div>
            <div class="f-detail">详情</div>
            <div class="f-ok">结果</div>
          </div>
          <div v-for="(log, i) in logs" :key="log.id" class="file-row" :class="{ odd: i % 2 === 1 }">
            <div class="f-time">{{ log.created_at }}</div>
            <div class="f-dir"><span class="dir-tag" :class="log.direction === 'IN' ? 'in' : 'out'">{{ log.direction === 'IN' ? '孪生调用' : 'OA回调' }}</span></div>
            <div class="f-action">{{ log.action }}</div>
            <div class="f-detail">{{ log.detail }}</div>
            <div class="f-ok"><el-tag :type="log.ok ? 'success' : 'danger'" size="small">{{ log.ok ? '成功' : '失败' }}</el-tag></div>
          </div>
        </div>
        <div v-if="!logs.length" class="empty-tip">暂无对接记录：数字孪生平台调用 OA 接口、或 OA 回调孪生时会记录在这里</div>
      </el-card>
    </div>
  `,
  data() {
    return {
      ov: { status_counts: [] },
      logs: [],
      cfgForm: { callback_url: '', api_key: '' },
      saving: false, testing: false,
    };
  },
  computed: {
    isAdmin() { return this.user.role === 'ADMIN'; },
  },
  methods: {
    async load() {
      try {
        this.ov = await API.get('/twin/overview');
        this.cfgForm.callback_url = this.ov.callback_url || '';
      } catch (e) { if (e.status !== 401) ElMessage.error(e.message); }
      this.loadLogs();
    },
    async loadLogs() {
      try {
        const d = await API.get('/twin/logs?page=1&page_size=50');
        this.logs = d.items;
      } catch (e) {}
    },
    async saveCfg() {
      this.saving = true;
      try {
        await API.put('/twin/config', { twin_callback_url: this.cfgForm.callback_url });
        ElMessage.success('配置已保存，立即生效');
        this.load();
      } catch (e) { ElMessage.error(e.message); }
      this.saving = false;
    },
    async doTestCallback() {
      this.testing = true;
      try {
        const r = await API.post('/twin/test-callback', {});
        ElMessage.success('回调测试成功：' + (r.detail || ''));
        this.loadLogs();
      } catch (e) { ElMessage.error(e.message); this.loadLogs(); }
      this.testing = false;
    },
  },
  mounted() { this.load(); },
};

/* ---------------- 根应用 ---------------- */
const RootApp = {
  components: {
    'dashboard-view': DashboardView,
    'orders-view': OrdersView,
    'repairs-view': RepairsView,
    'reports-view': ReportsView,
    'devices-view': DevicesView,
    'plans-view': PlansView,
    'announce-view': AnnounceView,
    'approvals-view': ApprovalsView,
    'files-view': FilesView,
    'twin-view': TwinView,
    'admin-view': AdminView,
  },
  template: `
    <div>
      <div v-if="!user" class="login-page">
        <div class="login-box">
          <div class="login-logo">OA</div>
          <div class="login-title">协同办公平台</div>
          <div class="login-sub">光伏清洁 · 协同办公</div>
          <el-form @submit.prevent>
            <el-input v-model="loginForm.username" size="large" placeholder="用户名" class="login-input">
              <template #prefix><span class="input-ico">👤</span></template>
            </el-input>
            <el-input v-model="loginForm.password" size="large" type="password" show-password placeholder="密码" class="login-input" @keyup.enter="doLogin">
              <template #prefix><span class="input-ico">🔒</span></template>
            </el-input>
            <el-button type="primary" size="large" class="login-btn" :loading="loginLoading" @click="doLogin">登 录</el-button>
          </el-form>
          <div class="login-tip">演示账号：admin / dispatcher / engineer1 · 密码均为 123456</div>
          <div class="login-tip" style="margin-top:6px">💡 需要桌面弹窗提醒（浏览器最小化也能收到）？<a class="link" href="/downloads/OATool-Notifier.exe" download>下载桌面提醒助手</a></div>
        </div>
        <div class="login-footer">OA协同办公平台 v1.0 · FastAPI + Vue3</div>
      </div>

      <el-container v-else class="layout">
        <el-aside width="220px" class="sidebar">
          <div class="sidebar-logo">
            <div class="logo-badge">OA</div>
            <div>
              <div class="logo-name">OA协同办公平台</div>
              <div class="logo-sub">光伏清洁</div>
            </div>
          </div>
          <el-menu :default-active="view" class="sidebar-menu" @select="changeView">
            <el-menu-item v-if="canView('dashboard')" index="dashboard"><span class="menu-ico">📊</span><span>工作台</span></el-menu-item>
            <el-menu-item v-if="canView('orders')" index="orders"><span class="menu-ico">📋</span><span>工单管理</span></el-menu-item>
            <el-menu-item v-if="canView('repairs')" index="repairs"><span class="menu-ico">📣</span><span>报修管理</span></el-menu-item>
            <el-menu-item v-if="canView('reports')" index="reports"><span class="menu-ico">📈</span><span>报表中心</span></el-menu-item>
            <el-menu-item v-if="canView('devices')" index="devices"><span class="menu-ico">🏭</span><span>设备台账</span></el-menu-item>
            <el-menu-item v-if="canView('plans')" index="plans"><span class="menu-ico">🗓️</span><span>保养计划</span></el-menu-item>
            <el-menu-item v-if="canView('announce')" index="announce"><span class="menu-ico">📢</span><span>公告通知</span><span v-if="unreadCount" class="menu-unread">{{ unreadCount > 99 ? '99+' : unreadCount }}</span></el-menu-item>
            <el-menu-item v-if="canView('approvals')" index="approvals"><span class="menu-ico">✅</span><span>审批中心</span></el-menu-item>
            <el-menu-item v-if="canView('files')" index="files"><span class="menu-ico">📁</span><span>文件共享</span></el-menu-item>
            <el-menu-item v-if="canView('twin')" index="twin"><span class="menu-ico">🔗</span><span>孪生对接</span></el-menu-item>
            <el-menu-item v-if="user.role !== 'ENGINEER'" index="screen"><span class="menu-ico">🖥️</span><span>大屏看板</span></el-menu-item>
            <el-menu-item v-if="user.role === 'ADMIN'" index="admin"><span class="menu-ico">🔐</span><span>权限管理</span></el-menu-item>
          </el-menu>
          <div class="sidebar-user">
            <div class="user-avatar">{{ user.real_name.charAt(0) }}</div>
            <div class="user-info">
              <div class="user-name">{{ user.real_name }}</div>
              <div class="user-role">{{ user.role_label }}<span v-if="user.title"> · {{ user.title }}</span></div>
            </div>
            <el-tooltip content="修改密码"><el-button circle size="small" class="logout-btn" @click="openPwd">🔑</el-button></el-tooltip>
            <el-tooltip content="退出登录"><el-button circle size="small" class="logout-btn" @click="logout">⏻</el-button></el-tooltip>
          </div>
        </el-aside>
        <el-container>
          <el-header class="header" height="56px">
            <div class="page-title">{{ pageTitles[view] }}</div>
            <div class="header-right">
              <span class="bell-btn" @click="openNotifyPermission"
                    :title="notifyState === 'granted' ? '桌面通知已开启' : notifyState === 'denied' ? '桌面通知被浏览器拦截，点击查看开启方法' : notifyState === 'unsupported' ? '局域网 HTTP 访问不支持浏览器通知，点击获取桌面提醒助手' : '点击开启桌面通知：最小化浏览器也能收到 Windows 提醒'">
                <span class="bell-ico" :class="notifyState === 'granted' ? 'on' : 'off'">{{ notifyState === 'granted' ? '🔔' : '🔕' }}</span>
              </span>
              <span class="ws-dot" :class="wsConnected ? 'on' : 'off'"></span>
              <span class="ws-text">{{ wsConnected ? '实时连接正常' : '实时连接已断开' }}</span>
              <span class="clock">{{ nowStr }}</span>
            </div>
          </el-header>
          <el-main class="main">
            <component :is="viewComponent" :user="user" :tick="wsTick" :open-id="linkedOrderId" @consume-open="linkedOrderId = null"></component>
          </el-main>
        </el-container>
      </el-container>

      <!-- 桌面通知引导 -->
      <el-dialog v-model="notifyDlg" :title="notifyState === 'unsupported' ? '获取桌面提醒助手' : '开启桌面通知'" width="500px" :close-on-click-modal="false">
        <div v-if="notifyState === 'unsupported'">
          <p style="line-height:1.9">局域网通过 <b>http://IP 地址</b> 访问时，浏览器出于安全规定不允许网页弹出系统通知（仅本机 127.0.0.1 或 HTTPS 网站可用），所以工程师电脑上的网页弹不出 Windows 通知。</p>
          <p style="line-height:1.9;margin-top:8px">解决办法：下载并运行<b>桌面提醒助手</b>——免安装、不需要 Python 和源码。登录一次后最小化即可，派给你的新工单（或工单超时）会弹出 Windows 右下角系统通知（带声音），浏览器关了也不影响。</p>
        </div>
        <div v-else>
          <p style="line-height:1.9">浏览器已拦截通知权限，请按以下步骤手动开启：</p>
          <ol style="line-height:2;padding-left:18px">
            <li>点击地址栏左侧的锁形图标（或信息图标）</li>
            <li>找到「通知」，选择「允许」</li>
            <li>刷新页面（Ctrl+F5）后生效</li>
          </ol>
          <p style="line-height:1.9;color:#909399">开启后，即使浏览器最小化或切到其他窗口，收到新工单也会弹出 Windows 右下角系统通知。若无法开启（如局域网 IP 访问），可改用桌面提醒助手：</p>
        </div>
        <template #footer>
          <el-button @click="notifyDlg = false">知道了</el-button>
          <el-button type="primary" plain tag="a" href="/downloads/桌面提醒助手使用说明.txt" download>使用说明</el-button>
          <el-button type="primary" tag="a" href="/downloads/OATool-Notifier.exe" download>下载桌面提醒助手（约 10MB）</el-button>
          <el-button type="primary" plain @click="openNotifierCfg">生成免输入配置</el-button>
          <el-button v-if="notifyState !== 'unsupported'" @click="notifyDlg = false; location.reload();">刷新页面</el-button>
        </template>
      </el-dialog>

      <!-- 生成桌面助手免输入配置 -->
      <el-dialog v-model="cfgDlg" title="生成桌面助手配置" width="500px" :close-on-click-modal="false">
        <p style="line-height:1.9">将为账号 <b>{{ user ? user.username : '' }}</b> 生成免输入配置文件，包含服务器地址（{{ serverOrigin }}）与登录信息，请妥善保管。</p>
        <el-form label-width="90px" @submit.prevent>
          <el-form-item label="登录密码"><el-input v-model="cfgPassword" type="password" show-password placeholder="输入当前账号的登录密码" @keyup.enter="downloadNotifierCfg"></el-input></el-form-item>
        </el-form>
        <p style="line-height:1.9;color:#909399">下载后把 <b>OA助手.ini</b> 放到 OATool-Notifier.exe 同一文件夹里，双击 exe 即自动登录，无需再输入任何内容。密码只在浏览器本地打包进文件，不会上传服务器。</p>
        <template #footer>
          <el-button @click="cfgDlg = false">取消</el-button>
          <el-button type="primary" @click="downloadNotifierCfg">生成并下载</el-button>
        </template>
      </el-dialog>

      <!-- 修改密码 -->
      <el-dialog v-model="pwdDlg" title="修改密码" width="400px" :close-on-click-modal="false">
        <el-form label-width="90px">
          <el-form-item label="原密码"><el-input v-model="pwdForm.old_password" type="password" show-password></el-input></el-form-item>
          <el-form-item label="新密码"><el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位"></el-input></el-form-item>
          <el-form-item label="确认新密码"><el-input v-model="pwdForm.confirm" type="password" show-password></el-input></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="pwdDlg = false">取消</el-button>
          <el-button type="primary" :loading="pwdLoading" @click="doChangePwd">确认修改</el-button>
        </template>
      </el-dialog>
    </div>
  `,
  data() {
    return {
      user: null,
      view: 'dashboard',
      pageTitles: { dashboard: '工作台', orders: '工单管理', repairs: '报修管理', reports: '报表中心', devices: '设备台账', plans: '保养计划', announce: '公告通知', approvals: '审批中心', files: '文件共享', twin: '孪生对接', admin: '权限管理' },
      loginForm: { username: '', password: '' },
      loginLoading: false,
      ws: null, wsConnected: false, wsTick: 0,
      nowStr: '', clockTimer: null,
      unreadCount: 0, unreadTimer: null,
      pwdDlg: false, pwdLoading: false,
      pwdForm: { old_password: '', new_password: '', confirm: '' },
      notifyState: 'unknown', notifyDlg: false,
      linkedOrderId: null, pendingOrderFromUrl: null,
      cfgDlg: false, cfgPassword: '',
    };
  },
  computed: {
    viewComponent() { return this.view + '-view'; },
    serverOrigin() { return location.origin; },
  },
  methods: {
    async doLogin() {
      if (!this.loginForm.username || !this.loginForm.password) { ElMessage.warning('请输入用户名和密码'); return; }
      // 必须在点击手势内同步请求通知权限，异步完成后再请求会被浏览器拦截
      this.requestNotifyPermission();
      this.loginLoading = true;
      try {
        const data = await API.post('/auth/login', this.loginForm);
        API.setToken(data.token);
        this.user = data.user;
        ElMessage.success('欢迎，' + data.user.real_name);
        this.connectWS();
        this.applyPendingOrder();
      } catch (e) { ElMessage.error(e.message); }
      this.loginLoading = false;
    },
    refreshNotifyState() {
      this.notifyState = window.Notification ? Notification.permission : 'unsupported';
    },
    requestNotifyPermission() {
      // 浏览器系统通知：本地访问(http://127.0.0.1)或 HTTPS 下生效，浏览器最小化也能弹到 Windows 通知中心
      if (window.Notification && Notification.permission === 'default') {
        Notification.requestPermission()
          .then((p) => { this.notifyState = p; })
          .catch(() => this.refreshNotifyState());
      } else {
        this.refreshNotifyState();
      }
    },
    async openNotifyPermission() {
      if (!window.Notification) { this.notifyState = 'unsupported'; this.notifyDlg = true; return; }
      if (Notification.permission === 'default') {
        const p = await Notification.requestPermission();
        this.notifyState = p;
        if (p === 'granted') {
          ElMessage.success('桌面通知已开启：最小化浏览器也能收到新工单提醒');
          this.showSystemNotification('OA协同办公平台 桌面通知', '设置成功！收到新工单时会在这里弹出提醒');
        } else {
          ElMessage.warning('未获得通知权限，无法弹出桌面通知');
        }
      } else if (Notification.permission === 'denied') {
        this.notifyDlg = true;
      } else if (Notification.permission === 'granted') {
        ElMessage.info('桌面通知已开启：收到新工单时会弹出 Windows 右下角提醒');
      }
    },
    showSystemNotification(title, body, tag) {
      if (window.Notification && Notification.permission === 'granted') {
        try {
          const n = new Notification(title, { body: body, tag: tag });
          n.onclick = function () { window.focus(); n.close(); };  // 点击通知回到页面
        } catch (e) {}
      }
    },
    async tryRestore() {
      if (!API.token) return;
      try {
        this.user = await API.get('/auth/me');
        this.connectWS();
        this.applyPendingOrder();
      } catch (e) { API.setToken(''); }
    },
    applyPendingOrder() {
      // 支持链接直达工单详情：/?open_order=工单ID（桌面助手弹窗点击跳转用）
      const p = new URLSearchParams(location.search).get('open_order');
      if (!p) return;
      this.pendingOrderFromUrl = p;
      history.replaceState(null, '', location.pathname);
      this.openLinkedOrder();
    },
    openLinkedOrder() {
      if (!this.pendingOrderFromUrl || !this.user) return;
      this.view = 'orders';
      this.linkedOrderId = Number(this.pendingOrderFromUrl);
      this.pendingOrderFromUrl = null;
    },
    logout() {
      if (this.ws) { this.ws.onclose = null; this.ws.close(); this.ws = null; }
      API.setToken('');
      this.user = null;
      this.wsConnected = false;
      this.view = 'dashboard';
    },
    connectWS() {
      if (!this.user || !API.token) return;  // 防御：未登录或无令牌不发起连接
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      this.ws = new WebSocket(proto + '://' + location.host + '/api/v1/ws?token=' + encodeURIComponent(API.token));
      this.ws.onopen = () => { this.wsConnected = true; };
      this.ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          ElNotification({
            title: '工单提醒',
            message: data.message || '有新动态',
            type: data.status === 'COMPLETED' ? 'success' : 'warning',
            duration: 5000,
          });
          const sysTitles = {
            dispatched: '新工单派单', created: '新工单待派发',
            accepted: '工单已接单', completed: '工单待验收', verified: '工单验收通过',
            verify_rejected: '工单验收驳回', cancelled: '工单已取消',
            repair_created: '新报修单', repair_approved: '报修已立项', repair_rejected: '报修被驳回',
            repair_withdrawn: '报修被撤回', approval_created: '新审批申请', approval_step: '审批流转',
            approval_approved: '审批已通过', approval_rejected: '审批被驳回', device_status_changed: '设备状态变更',
          };
          this.showSystemNotification(
            sysTitles[data.event] || 'OA协同办公平台 提醒',
            data.message || '有新动态',
            (data.event || '') + (data.workOrderId || data.approvalNo || data.requestNo || '')
          );
          this.wsTick++;
        } catch (e) {}
      };
      this.ws.onclose = () => {
        this.wsConnected = false;
        if (this.user) setTimeout(() => this.connectWS(), 3000);
      };
    },
    changeView(v) {
      if (v === 'screen') { window.open('/screen.html', '_blank'); return; }
      this.view = v;
    },
    canView(module) {
      return this.user && (this.user.role === 'ADMIN' || (this.user.permissions || []).includes(module));
    },
    async refreshUnread() {
      if (!this.user) return;
      if (this.user.role !== 'ADMIN' && !(this.user.permissions || []).includes('announce')) return;
      try {
        const d = await API.get('/announcements/unread-count');
        this.unreadCount = d.unread;
      } catch (e) {}
    },
    openPwd() {
      this.pwdForm = { old_password: '', new_password: '', confirm: '' };
      this.pwdDlg = true;
    },
    async doChangePwd() {
      if (this.pwdForm.new_password.length < 6) { ElMessage.warning('新密码至少 6 位'); return; }
      if (this.pwdForm.new_password !== this.pwdForm.confirm) { ElMessage.warning('两次输入的新密码不一致'); return; }
      this.pwdLoading = true;
      try {
        await API.post('/auth/change-password', {
          old_password: this.pwdForm.old_password,
          new_password: this.pwdForm.new_password,
        });
        ElMessage.success('密码修改成功');
        this.pwdDlg = false;
      } catch (e) { ElMessage.error(e.message); }
      this.pwdLoading = false;
    },
    openNotifierCfg() {
      this.notifyDlg = false;
      this.cfgPassword = '';
      this.cfgDlg = true;
    },
    downloadNotifierCfg() {
      if (!this.cfgPassword) { ElMessage.warning('请输入登录密码'); return; }
      const b64 = (s) => btoa(unescape(encodeURIComponent(s)));  // 与桌面助手同一套 base64(UTF-8) 编码
      const cfg = {
        base: location.origin,
        username: b64(this.user.username),
        password: b64(this.cfgPassword),
      };
      const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'OA助手.ini';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      ElMessage.success('配置已下载：放到 OATool-Notifier.exe 同目录，双击 exe 即可免输入使用');
      this.cfgDlg = false;
    },
    updateClock() { this.nowStr = new Date().toLocaleString('zh-CN', { hour12: false }); },
    on401() {
      // 登录态失效：断开 WS、清空状态，回到登录页
      if (this.ws) { this.ws.onclose = null; this.ws.close(); this.ws = null; }
      this.user = null;
      this.wsConnected = false;
      this.view = 'dashboard';
    },
  },
  mounted() {
    this.updateClock();
    this.clockTimer = setInterval(this.updateClock, 1000);
    this.refreshNotifyState();
    window.addEventListener('oatool-401', this.on401);
    window.addEventListener('focus', this.refreshNotifyState);
    this.tryRestore();
    this.unreadTimer = setInterval(this.refreshUnread, 60000);
    setTimeout(this.refreshUnread, 2000);
  },
  beforeUnmount() {
    if (this.clockTimer) clearInterval(this.clockTimer);
    if (this.unreadTimer) clearInterval(this.unreadTimer);
    window.removeEventListener('oatool-401', this.on401);
    window.removeEventListener('focus', this.refreshNotifyState);
  },
};

const app = createApp(RootApp);
if (window.ElementPlusLocaleZhCn) app.use(ElementPlus, { locale: window.ElementPlusLocaleZhCn });
else app.use(ElementPlus);
app.mount('#app');
