const state = { communities: [], selected: null };
const API_BASE = window.HOUSE_API_BASE || 'http://localhost:8787';

const $ = (selector) => document.querySelector(selector);
const text = (value, fallback = '待核验') => value === null || value === undefined || value === '' ? fallback : value;

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

function renderList() {
  const keyword = ($('#search')?.value || '').trim().toLowerCase();
  const filtered = state.communities.filter(c => c.standard_name.toLowerCase().includes(keyword));
  $('#community-count').textContent = `${filtered.length} / ${state.communities.length}`;
  $('#community-list').innerHTML = filtered.length ? filtered.map(c => `<div class="community-item ${c.id === state.selected ? 'active' : ''}" data-id="${c.id}"><h3>${c.standard_name}</h3><p>${text(c.address, '地址待核验')}</p><span class="tag ${c.verification_status === 'verified' ? 'ok' : ''}">${c.verification_status === 'verified' ? '已核验' : '待核验'}</span></div>`).join('') : '<div class="empty">没有匹配的小区</div>';
  document.querySelectorAll('.community-item').forEach(item => item.addEventListener('click', () => { state.selected = item.dataset.id; renderList(); renderDetail(); }));
}

function renderDetail() {
  const c = state.communities.find(item => item.id === state.selected);
  if (!c) { $('#detail').innerHTML = '<div class="empty">请选择一个小区</div>'; return; }
  const missing = new Set(c.audit?.missing_fields || []);
  const field = (key, label, valueKey = key) => `<div class="field"><label>${label}</label><strong class="${missing.has(key) ? 'missing' : ''}">${missing.has(key) ? '待核验' : text(c[valueKey])}</strong></div>`;
  const checks = [['address','地址'],['longitude','经度'],['latitude','纬度'],['market_area','市场板块'],['verification_status','核验状态'],['administrative_area','行政区']];
  const market = c.market || { history: [], listings: [] };
  const money = (value) => value === null || value === undefined ? '未知' : `${Number(value).toLocaleString('zh-CN')} 万`;
  const price = (value) => value === null || value === undefined ? '未知' : `${Number(value).toLocaleString('zh-CN')} 元/㎡`;
  const historyRows = market.history.length ? market.history.map(item => `<div class="market-row"><div><strong>${text(item.event_date, '日期未知')}</strong><span>${item.bedrooms ? `${item.bedrooms}室` : '户型未知'} · ${text(item.area_sqm, '面积未知')}㎡ · ${text(item.floor_text, '楼层未知')} · ${text(item.source?.name, '来源未知')}</span></div><div class="market-price">${money(item.total_price)}<small>${price(item.unit_price)}</small></div><a href="${item.source_url || '#'}" target="_blank" rel="noreferrer">来源</a></div>`).join('') : '<div class="empty">暂无可核验的成交样本</div>';
  const listingRows = market.listings.length ? market.listings.map(item => `<div class="market-row"><div><strong>${item.bedrooms ? `${item.bedrooms}室` : '户型未知'} · ${text(item.area_sqm, '面积未知')}㎡</strong><span>${text(item.floor_text, '楼层未知')} · ${text(item.source?.name, '来源未知')} · ${item.freshness_status === 'stale' ? '已过期' : item.freshness_status === 'observed' ? '已观察' : '状态未知'}</span></div><div class="market-price">${money(item.total_price)}<small>${price(item.unit_price)}</small></div><a href="${item.source_url || '#'}" target="_blank" rel="noreferrer">查看</a></div>`).join('') : '<div class="empty">暂无可核验的在售房源</div>';
  $('#detail').innerHTML = `<div class="detail-header"><div><p class="eyebrow">COMMUNITY PROFILE</p><h2>${c.standard_name}</h2><div class="detail-sub">${text(c.administrative_area_name)} · 数据截至 ${text(market.data_as_of, '未知')}</div></div><span class="detail-status ${c.verification_status === 'verified' ? 'ok' : ''}">${c.verification_status === 'verified' ? '已核验' : '待补充证据'}</span></div><div class="detail-section"><h3>核心信息</h3><div class="field-grid">${field('address','地址')}${field('longitude','经度')}${field('latitude','纬度')}${field('market_area','市场板块','market_area_name')}${field('property_type','物业类型')}${field('first_completed_year','竣工年份')}</div></div><div class="detail-section"><h3>完整性审计 · ${c.audit?.status === 'complete' ? '已完成' : `缺 ${missing.size} 项`}</h3><div class="audit-list">${checks.map(([key,label]) => `<div class="audit-item ${missing.has(key) ? 'missing' : ''}"><i>${missing.has(key) ? '!' : '✓'}</i>${label}</div>`).join('')}</div></div><div class="detail-section market-section"><div class="market-heading"><div><h3>历史成交样本</h3><p>成交与挂牌严格分开，按签约日期升序</p></div><span class="count-pill">${market.history.length} 条</span></div>${historyRows}</div><div class="detail-section market-section"><div class="market-heading"><div><h3>当前在售</h3><p>公开挂牌快照，显示最近观察状态</p></div><span class="count-pill">${market.listings.length} 套</span></div>${listingRows}</div><div class="detail-section"><h3>关联数据</h3><div class="field-grid">${Object.entries(c.audit?.related_counts || {}).map(([key,value]) => `<div class="field"><label>${key.replaceAll('_',' ')}</label><strong>${value}</strong></div>`).join('')}</div></div>`;
}

$('#search').addEventListener('input', renderList);
loadData().catch(error => { $('#detail').innerHTML = `<div class="empty">${error.message}</div>`; });
