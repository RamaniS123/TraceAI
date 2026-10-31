const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
 if (!process.env.TRACEAI_UI_BASE_URL || !process.env.TRACEAI_UI_API_TOKEN) throw new Error('Set TRACEAI_UI_BASE_URL and TRACEAI_UI_API_TOKEN for an isolated synthetic test service.');
 const screenshots = path.resolve('reports/browser');
 fs.mkdirSync(screenshots, {recursive:true});
 const browser = await chromium.launch({headless:true, executablePath:process.env.TRACEAI_CHROMIUM_PATH || undefined});
 try {
  const page = await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.TRACEAI_UI_BASE_URL);
  await page.getByText('Service healthy',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Fill example',exact:true}).click();
  const interaction = await page.locator('#interaction-id').inputValue();
  await page.getByRole('button',{name:'Store event'}).click();
  await page.getByText('Connect your API token in step 1 first.',{exact:true}).waitFor();
  await page.getByLabel('API token',{exact:true}).fill(process.env.TRACEAI_UI_API_TOKEN);
  await page.getByRole('button',{name:'Use token',exact:true}).click();
  assert.equal(await page.locator('#api-token').inputValue(),'');
  await page.getByLabel('Event data',{exact:false}).fill(JSON.stringify({note:'<img src=x onerror="window.uiInjected=true">'}).slice(0,-1)+',"precise":0.12345678901234567890123456789}');
  await page.getByRole('button',{name:'Store event'}).click();
  await page.waitForFunction(()=>document.querySelector('#submit-status').textContent.startsWith('Stored event'));
  await page.getByRole('button',{name:'Find events',exact:true}).click();
  await page.getByText('Retrieved from the connected database.',{exact:true}).waitFor();
  assert.equal(await page.locator('#result-id').textContent(),interaction);
  assert.equal(await page.locator('.event-card').count(),1);
  await page.getByText('View event details',{exact:true}).click();
  assert.ok((await page.locator('.event-card pre').textContent()).includes('<img'));
  assert.equal(await page.locator('.event-card img').count(),0);
  assert.equal(await page.evaluate(()=>window.uiInjected),undefined);
  assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
  await page.screenshot({path:path.join(screenshots,'desktop.png'),fullPage:true});
  // An exact repeat is shown as a duplicate, never a second copy.
  await page.getByRole('button',{name:'Store event'}).click();
  await page.waitForFunction(()=>document.querySelector('#submit-status').textContent.includes('No duplicate was created'));
  // Exercise actual Phase 4 reports: missing/output order warnings and linked reviews.
  const baseEvent = {interactionId:interaction, modelVersion:'model-2', applicationVersion:'app-2'};
  const stamp = Date.now();
  const reviewId = 'ui-review-'+stamp;
  async function postRecord(fields) {
    const response = await page.request.post(process.env.TRACEAI_UI_BASE_URL+'/api/v1/events', {
      headers:{Authorization:'Bearer '+process.env.TRACEAI_UI_API_TOKEN}, data:{...baseEvent,...fields}});
    assert.equal(response.status(),201);
  }
  await postRecord({eventId:reviewId,eventType:'review.completed',occurredAt:new Date(stamp-10000).toISOString(),data:{reviewerId:'reviewer-1',action:'override',reason:'<img src=x onerror="window.uiInjected=true">'}});
  await postRecord({eventId:'ui-end-'+stamp,eventType:'interaction.completed',occurredAt:new Date(stamp+10000).toISOString(),data:{}});
  await postRecord({eventId:'ui-fix-'+stamp,eventType:'record.corrected',occurredAt:new Date(stamp+20000).toISOString(),data:{correctsEventId:reviewId,reason:'Synthetic review correction'}});
  await page.getByRole('button',{name:'Find events',exact:true}).click();
  await page.getByText('Retrieved from the connected database.',{exact:true}).waitFor();
  for (const title of ['Missing event','Event out of order','Correction recorded']) await page.locator('#warning-list').getByRole('heading',{name:title,exact:true}).first().waitFor();
  await page.getByRole('button',{name:'Load audit report',exact:true}).click();
  await page.locator('#audit-report').waitFor();
  assert.ok((await page.locator('#report-reviews').textContent()).includes('reviewer-1 · override'));
  assert.ok((await page.locator('#report-corrections').textContent()).includes(reviewId));
  assert.ok((await page.locator('#report-metadata').textContent()).includes('model-2'));
  assert.ok((await page.locator('#report-disclaimer').textContent()).includes('does not certify legal compliance'));
  assert.equal(await page.locator('#audit-report img').count(),0);
  assert.equal(await page.evaluate(()=>window.uiInjected),undefined);
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button',{name:'Download report JSON',exact:true}).click();
  const download = await downloadEvent;
  const downloaded = path.join(screenshots,'audit-report.json');
  await download.saveAs(downloaded);
  const raw = fs.readFileSync(downloaded,'utf8');
  assert.ok(raw.includes('0.12345678901234567890123456789'));
  assert.ok(!raw.includes(process.env.TRACEAI_UI_API_TOKEN));
  assert.equal(JSON.parse(raw).events.length,4);
  await page.screenshot({path:path.join(screenshots,'desktop-report.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
  await page.screenshot({path:path.join(screenshots,'mobile-report.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1100});
  await page.getByRole('button',{name:'Store event'}).click();
  await page.waitForFunction(()=>document.querySelector('#submit-status').textContent.includes('No duplicate was created'));
  assert.equal(await page.locator('#audit-report').isVisible(),false);
  assert.equal(await page.locator('#interaction-result').isVisible(),false);
  await page.getByRole('button',{name:'Find events',exact:true}).click();
  await page.getByText('Retrieved from the connected database.',{exact:true}).waitFor();
  const reportPattern = '**/api/v1/interactions/*/report';
  for (const status of [401,404,503]) {
    await page.route(reportPattern,route=>route.fulfill({status,contentType:'application/json',body:'{}'}));
    await page.getByRole('button',{name:'Load audit report',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#report-status').classList.contains('error'));
    assert.equal(await page.locator('#audit-report').isVisible(),false);
    assert.equal(await page.locator('#download-report').isDisabled(),true);
    await page.unroute(reportPattern);
  }
  await page.getByRole('button',{name:'Load audit report',exact:true}).click();
  await page.locator('#audit-report').waitFor();
  // A delayed response cannot redisplay records after disconnect.
  let release, entered;
  const gate = new Promise(resolve=>{release=resolve});
  const started = new Promise(resolve=>{entered=resolve});
  await page.route(reportPattern,async route=>{const response=await route.fetch();entered();await gate;await route.fulfill({response});});
  await page.getByRole('button',{name:'Load audit report',exact:true}).click();
  await started;
  await page.getByRole('button',{name:'Disconnect',exact:true}).click();
  const finished = page.waitForResponse(response=>response.url().endsWith('/report'));
  release();await finished;await page.waitForTimeout(100);
  assert.equal(await page.locator('#audit-report').isVisible(),false);
  assert.equal(await page.locator('#report-reviews').textContent(),'');
  await page.unroute(reportPattern);

  assert.equal(await page.locator('#interaction-result').isVisible(),false);
  assert.equal(await page.locator('.event-card').count(),0);
  await page.getByLabel('API token',{exact:true}).fill('synthetic-invalid-token');
  await page.getByRole('button',{name:'Use token',exact:true}).click();
  await page.getByRole('button',{name:'Find events',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#lookup-status').textContent.includes('token was rejected'));
  await page.getByLabel('API token',{exact:true}).fill(process.env.TRACEAI_UI_API_TOKEN);
  await page.getByRole('button',{name:'Use token',exact:true}).click();
  const cleanId = 'clean-ui-'+stamp;
  await postRecord({interactionId:cleanId,eventId:'clean-event-'+stamp,eventType:'interaction.started',occurredAt:new Date(stamp).toISOString(),data:{}});
  await page.locator('#lookup-id').fill(cleanId);
  await page.getByRole('button',{name:'Find events',exact:true}).click();
  await page.getByText('Retrieved from the connected database.',{exact:true}).waitFor();
  assert.equal(await page.locator('#warning-list article').count(),0);
  await page.getByText('No timeline warnings were reported for these records.',{exact:true}).waitFor();
  // The report belongs to the displayed interaction, even if the search input changes.
  await page.locator('#lookup-id').fill('not-the-displayed-interaction');
  await page.getByRole('button',{name:'Load audit report',exact:true}).click();
  await page.locator('#audit-report').waitFor();
  await page.getByText('No human reviews recorded.',{exact:true}).waitFor();
  await page.getByText('No linked corrections recorded.',{exact:true}).waitFor();
  assert.equal(await page.locator('#result-id').textContent(),cleanId);
  await page.getByLabel('Interaction ID',{exact:true}).last().fill('does-not-exist');
  await page.getByRole('button',{name:'Find events',exact:true}).click();
  await page.getByText('No records were found for that interaction ID.',{exact:true}).waitFor();
  await page.reload();
  await page.getByText('No token connected',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(screenshots,'mobile.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
  assert.deepEqual(errors,[]);
  console.log('PASS: browser events, Phase 4 warnings/reviews/corrections, precise JSON download, safe rendering, report errors/retry, disconnect race and mobile layout');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
