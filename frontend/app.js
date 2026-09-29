const state = {
  communities: [], selected: null, externalSelected: null, searchResults: [],
  searchQuery: '', searchStatus: 'idle', searchMessage: '', searchTimer: null, searchSequence: 0,
};
const API_BASE = window.HOUSE_API_BASE || 'http://localhost:8787';
const $ = (selector) => document.querySelector(selector);
const text = (value, fallback = '待核验') => value === null || value === undefined || value === '' ? fallback : value;
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);

async function loadData() {
  const response = await fetch(`${API_BASE}/api/v1/communities`);
  if (!response.ok) throw new Error('无法读取小区数据');
  state.communities = await response.json();
  await Promise.all(state.communities.map(async (community) => {
    const quality = await fetch(`${API_BASE}/api/v1/communities/${community.id}/quality`);
    if (quality.ok) community.audit = await quality.json();
    const market = await fetch(`${API_BASE}/api/v1/communities/${community.id}/market`);
    if (market.ok) community.market = await market.json();
  }));
  state.selected = state.communities[0]?.id;
  renderSummary(); renderList(); renderDetail();
}

function renderSummary() {
  const total = state.communities.length;
  const verified = state.communities.filter(c => c.verification_status === 'verified').length;
  const complete = state.communities.filter(c => c.audit?.status === 'complete').length;
  $('#summary').innerHTML = [
    ['观察池', total, '个小区'], ['已核验', verified, '个'], ['数据完整', complete, '个'], ['待处理缺口', state.communities.reduce((n,c) => n + (c.audit?.missing_fields?.length || 0), 0), '项']
  ].map(([label,value,suffix]) => `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}<small> ${suffix}</small></div></div>`).join('');
}

function localMatches(keyword) {
  return state.communities.filter(c => c.standard_name.toLowerCase().includes(keyword.toLowerCase())).map(c => ({ ...c, scope: 'local' }));
}

function currentResults() {
  const keyword = ($('#search')?.value || '').trim();
  if (!keyword) return state.communities.map(c => ({ ...c, scope: 'local' }));
  if (state.searchQuery === keyword && state.searchResults.length) return state.searchResults;
  return localMatches(keyword);
}

function renderList() {
  const keyword = ($('#search')?.value || '').trim();
  const results = currentResults();
  $('#community-count').textContent = keyword ? `${results.length} 个结果` : `${state.communities.length} 个`;
  const items = results.map(c => {
    const external = c.scope === 'external';
    const subtitle = external ? `${escapeHtml(text(c.area_label, '区域未知'))} · 挂牌 ${Number(c.listing_count || 0)} 套` : escapeHtml(text(c.address, '地址待核验'));
    const badge = external ? '<span class="tag external">TMSF 外部索引</span>' : `<span class="tag ${c.verification_status === 'verified' ? 'ok' : ''}">${c.verification_status === 'verified' ? '已核验' : '待核验'}</span>`;
    return `<div class="community-item ${c.id === state.selected ? 'active' : ''}" data-id="${escapeHtml(c.id)}" data-scope="${c.scope}"><h3>${escapeHtml(c.standard_name)}</h3><p>${subtitle}</p>${badge}</div>`;
  }).join('');
  let helper = '';
  if (keyword.length === 1) helper = '<div class="search-hint">再输入 1 个字，搜索全杭州小区</div>';
  else if (state.searchStatus === 'loading') helper = '<div class="search-hint">正在查询透明售房网公开小区索引…</div>';
  else if (state.searchStatus === 'unavailable') helper = `<div class="search-hint warning">外部搜索暂不可用，已显示本地结果。${escapeHtml(state.searchMessage)}</div>`;
  else if (keyword && !results.length) helper = '<div class="empty">没有匹配的小区</div>';
  $('#community-list').innerHTML = items + helper;
  document.querySelectorAll('.community-item').forEach(item => item.addEventListener('click', () => {
    state.selected = item.dataset.id;
    state.externalSelected = item.dataset.scope === 'external' ? results.find(c => c.id === item.dataset.id) : null;
    renderList(); renderDetail();
  }));
}

function renderExternalDetail(c) {
  $('#detail').innerHTML = `<div class="detail-header"><div><p class="eyebrow">TMSF SEARCH RESULT</p><h2>${escapeHtml(c.standard_name)}</h2><div class="detail-sub">${escapeHtml(text(c.area_label, '区域未知'))} · 透明售房网公开小区索引</div></div><span class="detail-status external">外部候选</span></div><div class="detail-section"><h3>公开索引摘要</h3><div class="field-grid"><div class="field"><label>行政区 / 板块</label><strong>${escapeHtml(text(c.area_label))}</strong></div><div class="field"><label>当前挂牌计数</label><strong>${Number(c.listing_count || 0)} 套</strong></div><div class="field"><label>出租计数</label><strong>${Number(c.rent_count || 0)} 套</strong></div><div class="field"><label>近 30 日签约计数</label><strong>${Number(c.signed_count_30d || 0)} 套</strong></div><div class="field"><label>TMSF 小区 ID</label><strong>${escapeHtml(c.external_id)}</strong></div><div class="field"><label>本地状态</label><strong class="missing">尚未加入观察池</strong></div></div></div><div class="detail-section external-note"><h3>数据边界</h3><p>这是全杭州公开小区索引的搜索结果，不代表该小区已经完成本地主数据核验，也不会自动写入数据库。详情页采集仍遵循低频访问、触发风控即停止的规则。</p><a class="source-button" href="${escapeHtml(c.source_url)}" target="_blank" rel="noreferrer">查看 TMSF 公开小区页 ↗</a></div>`;
}

function renderDetail() {
  if (state.externalSelected && state.selected === state.externalSelected.id) { renderExternalDetail(state.externalSelected); return; }
  const c = state.communities.find(item => item.id === state.selected);
  if (!c) { $('#detail').innerHTML = '<div class="empty">请选择一个小区</div>'; return; }
  const missing = new Set(c.audit?.missing_fields || []);
  const field = (key, label, valueKey = key) => `<div class="field"><label>${label}</label><strong class="${missing.has(key) ? 'missing' : ''}">${missing.has(key) ? '待核验' : escapeHtml(text(c[valueKey]))}</strong></div>`;
  const checks = [['address','地址'],['longitude','经度'],['latitude','纬度'],['market_area','市场板块'],['verification_status','核验状态'],['administrative_area','行政区']];
  const market = c.market || { history: [], listings: [] };
  const money = (value) => value === null || value === undefined ? '未知' : `${Number(value).toLocaleString('zh-CN')} 万`;
  const price = (value) => value === null || value === undefined ? '未知' : `${Number(value).toLocaleString('zh-CN')} 元/㎡`;
  const historyRows = market.history.length ? market.history.map(item => `<div class="market-row"><div><strong>${escapeHtml(text(item.event_date, '日期未知'))}</strong><span>${item.bedrooms ? `${item.bedrooms}室` : '户型未知'} · ${escapeHtml(text(item.area_sqm, '面积未知'))}㎡ · ${escapeHtml(text(item.floor_text, '楼层未知'))} · ${escapeHtml(text(item.source?.name, '来源未知'))}</span></div><div class="market-price">${money(item.total_price)}<small>${price(item.unit_price)}</small></div><a href="${escapeHtml(item.source_url || '#')}" target="_blank" rel="noreferrer">来源</a></div>`).join('') : '<div class="empty">暂无可核验的成交样本</div>';
  const listingRows = market.listings.length ? market.listings.map(item => `<div class="market-row"><div><strong>${item.bedrooms ? `${item.bedrooms}室` : '户型未知'} · ${escapeHtml(text(item.area_sqm, '面积未知'))}㎡</strong><span>${escapeHtml(text(item.floor_text, '楼层未知'))} · ${escapeHtml(text(item.source?.name, '来源未知'))} · ${item.freshness_status === 'stale' ? '已过期' : item.freshness_status === 'observed' ? '已观察' : '状态未知'}</span></div><div class="market-price">${money(item.total_price)}<small>${price(item.unit_price)}</small></div><a href="${escapeHtml(item.source_url || '#')}" target="_blank" rel="noreferrer">查看</a></div>`).join('') : '<div class="empty">暂无可核验的在售房源</div>';
  $('#detail').innerHTML = `<div class="detail-header"><div><p class="eyebrow">COMMUNITY PROFILE</p><h2>${escapeHtml(c.standard_name)}</h2><div class="detail-sub">${escapeHtml(text(c.administrative_area_name))} · 数据截至 ${escapeHtml(text(market.data_as_of, '未知'))}</div></div><span class="detail-status ${c.verification_status === 'verified' ? 'ok' : ''}">${c.verification_status === 'verified' ? '已核验' : '待补充证据'}</span></div><div class="detail-section"><h3>核心信息</h3><div class="field-grid">${field('address','地址')}${field('longitude','经度')}${field('latitude','纬度')}${field('market_area','市场板块','market_area_name')}${field('property_type','物业类型')}${field('first_completed_year','竣工年份')}</div></div><div class="detail-section"><h3>完整性审计 · ${c.audit?.status === 'complete' ? '已完成' : `缺 ${missing.size} 项`}</h3><div class="audit-list">${checks.map(([key,label]) => `<div class="audit-item ${missing.has(key) ? 'missing' : ''}"><i>${missing.has(key) ? '!' : '✓'}</i>${label}</div>`).join('')}</div></div><div class="detail-section market-section"><div class="market-heading"><div><h3>历史成交样本</h3><p>成交与挂牌严格分开，按签约日期升序</p></div><span class="count-pill">${market.history.length} 条</span></div>${historyRows}</div><div class="detail-section market-section"><div class="market-heading"><div><h3>当前在售</h3><p>公开挂牌快照，显示最近观察状态</p></div><span class="count-pill">${market.listings.length} 套</span></div>${listingRows}</div><div class="detail-section"><h3>关联数据</h3><div class="field-grid">${Object.entries(c.audit?.related_counts || {}).map(([key,value]) => `<div class="field"><label>${escapeHtml(key.replaceAll('_',' '))}</label><strong>${value}</strong></div>`).join('')}</div></div>`;
}

async function runSearch(keyword) {
  const sequence = ++state.searchSequence;
  state.searchQuery = keyword; state.searchStatus = 'loading'; state.searchMessage = ''; state.searchResults = localMatches(keyword); renderList();
  try {
    const response = await fetch(`${API_BASE}/api/v1/community-search?q=${encodeURIComponent(keyword)}&limit=20`);
    if (!response.ok) throw new Error(`搜索服务返回 ${response.status}`);
    const payload = await response.json();
    if (sequence !== state.searchSequence || ($('#search').value || '').trim() !== keyword) return;
    state.searchResults = payload.results || [];
    state.searchStatus = payload.external_status === 'succeeded' ? 'succeeded' : 'unavailable';
    state.searchMessage = payload.external_message || '';
  } catch (error) {
    if (sequence !== state.searchSequence) return;
    state.searchStatus = 'unavailable'; state.searchMessage = error.message;
  }
  renderList();
}

$('#search').addEventListener('input', (event) => {
  const keyword = event.target.value.trim();
  clearTimeout(state.searchTimer); state.searchSequence += 1; state.searchQuery = keyword;
  state.searchResults = localMatches(keyword); state.searchStatus = 'idle'; state.searchMessage = ''; renderList();
  if (keyword.length >= 2) state.searchTimer = setTimeout(() => runSearch(keyword), 300);
});
loadData().catch(error => { $('#detail').innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; });
