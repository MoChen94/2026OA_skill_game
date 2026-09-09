/* API 请求封装：统一携带 JWT、统一错误提示格式 */
const API = {
  base: '/api/v1',
  token: localStorage.getItem('oatool_token') || '',

  setToken(t) {
    this.token = t || '';
    if (t) localStorage.setItem('oatool_token', t);
    else localStorage.removeItem('oatool_token');
  },

  async request(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (this.token) headers.Authorization = 'Bearer ' + this.token;
    let res;
    try {
      res = await fetch(this.base + path, { ...options, headers });
    } catch (e) {
      throw { status: 0, message: '无法连接服务器，请检查服务是否启动' };
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let msg = '请求失败';
      if (typeof data.detail === 'string') msg = data.detail;
      else if (Array.isArray(data.detail)) msg = '请求参数错误';
      if (res.status === 401) {
        this.setToken('');
        // 通知应用：登录态失效，界面应立即回到登录页（防止空 token 反复重连）
        if (typeof window !== 'undefined' && window.dispatchEvent) {
          window.dispatchEvent(new CustomEvent('oatool-401'));
        }
      }
      throw { status: res.status, message: msg };
    }
    return data;
  },

  get(path) { return this.request(path); },
  post(path, body) { return this.request(path, { method: 'POST', body: JSON.stringify(body) }); },
  put(path, body) { return this.request(path, { method: 'PUT', body: JSON.stringify(body) }); },
  del(path) { return this.request(path, { method: 'DELETE' }); },

  // 上传文件（multipart/form-data）。onProgress(percent) 回调实时进度（0-100）
  upload(path, formData, onProgress) {
    const self = this;
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', self.base + path);
      if (self.token) xhr.setRequestHeader('Authorization', 'Bearer ' + self.token);
      if (onProgress) {
        xhr.upload.onprogress = function (e) {
          if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
        };
      }
      xhr.onload = function () {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (e) {}
        if (xhr.status >= 200 && xhr.status < 300) { resolve(data); return; }
        let msg = '上传失败';
        if (typeof data.detail === 'string') msg = data.detail;
        if (xhr.status === 401) {
          self.setToken('');
          if (typeof window !== 'undefined' && window.dispatchEvent) {
            window.dispatchEvent(new CustomEvent('oatool-401'));
          }
        }
        reject({ status: xhr.status, message: msg });
      };
      xhr.onerror = function () { reject({ status: 0, message: '无法连接服务器，请检查服务是否启动' }); };
      xhr.send(formData);
    });
  },

  // 拉取文件内容为 blob（带鉴权的图片预览等），返回 object URL
  async fetchObjectUrl(path) {
    const headers = {};
    if (this.token) headers.Authorization = 'Bearer ' + this.token;
    const res = await fetch(this.base + path, { headers });
    if (!res.ok) throw { message: '加载文件失败' };
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },

  // 下载文件（Excel 导出等），自动解析文件名并触发浏览器下载
  async download(path) {
    const headers = {};
    if (this.token) headers.Authorization = 'Bearer ' + this.token;
    let res;
    try {
      res = await fetch(this.base + path, { headers });
    } catch (e) {
      throw { message: '无法连接服务器，请检查服务是否启动' };
    }
    if (!res.ok) {
      let msg = '导出失败';
      try {
        const d = await res.json();
        if (typeof d.detail === 'string') msg = d.detail;
      } catch (e) {}
      throw { status: res.status, message: msg };
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    let name = 'export.xlsx';
    // Starlette 的文件下载头是小写 utf-8，导出接口是大写 UTF-8，两种都要兼容
    const m = cd.match(/filename\*=utf-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/);
    if (m) {
      try { name = decodeURIComponent(m[1]); } catch (e) { name = m[1]; }
      // 兼容 \uXXXX 转义形式的文件名
      name = name.replace(/\\u([0-9a-fA-F]{4})/g, function (_, h) { return String.fromCharCode(parseInt(h, 16)); });
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
