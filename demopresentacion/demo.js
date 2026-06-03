const { chromium } = require('playwright');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const ffmpegPath = require('ffmpeg-static');

const BASE_URL = 'http://127.0.0.1:8002';
const USERNAME = `demouser${Date.now()}`;
const PASSWORD = 'DemoPass123!';
const AUDIO_PATH = path.resolve(__dirname, '..', 'media', 'audio', 'videoplayback.m4a');
const OUTPUT_DIR = path.resolve(__dirname);
const VIDEO_DIR = path.join(OUTPUT_DIR, 'videos');

(async () => {
  if (!fs.existsSync(VIDEO_DIR)) fs.mkdirSync(VIDEO_DIR, { recursive: true });
  // Limpiar screenshots anteriores
  fs.readdirSync(OUTPUT_DIR).forEach(f => {
    if (f.endsWith('.png')) fs.unlinkSync(path.join(OUTPUT_DIR, f));
  });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    recordVideo: {
      dir: VIDEO_DIR,
      size: { width: 1280, height: 720 },
    },
  });
  const page = await context.newPage();

  const wait = (ms) => page.waitForTimeout(ms);
  const screenshot = async (name) => {
    try {
      await page.screenshot({ path: path.join(OUTPUT_DIR, `${name}.png`), fullPage: false });
    } catch (e) {}
  };
  const safeClick = async (sel, opts = {}) => {
    try {
      await page.waitForSelector(sel, { timeout: opts.timeout || 10000 });
      await page.click(sel);
    } catch (e) {
      console.log('Click failed:', sel, e.message);
    }
  };

  try {
    // ========== 1. Landing page ==========
    console.log('1. Landing page');
    await page.goto(`${BASE_URL}/mini`, { waitUntil: 'networkidle' });
    await wait(2000);
    await page.evaluate(() => window.scrollBy({ top: 500, behavior: 'smooth' }));
    await wait(2000);
    await page.evaluate(() => window.scrollBy({ top: 700, behavior: 'smooth' }));
    await wait(2000);
    await screenshot('01-landing');

    // ========== 2. Registro ==========
    console.log('2. Registro');
    await page.goto(`${BASE_URL}/registro/`, { waitUntil: 'networkidle' });
    await wait(1500);
    await page.fill('input[name="username"]', USERNAME);
    await page.fill('input[name="email"]', `${USERNAME}@demo.com`);
    await page.fill('input[name="password1"]', PASSWORD);
    await page.fill('input[name="password2"]', PASSWORD);
    await wait(800);
    await page.click('button[type="submit"]');
    await page.waitForLoadState('networkidle', { timeout: 20000 });
    await wait(2000);
    await screenshot('02-dashboard');

    // ========== 3. Crear curso ==========
    console.log('3. Crear curso');
    await page.goto(`${BASE_URL}/cursos/nuevo/`, { waitUntil: 'networkidle' });
    await wait(1500);
    await page.fill('input[name="name"]', 'Biología General Demo');
    await page.fill('input[name="academic_period"]', '2026-1');
    await page.fill('textarea[name="description"]', 'Curso de introducción a la biología para demostración.');
    await page.fill('input[name="instructor"]', 'Prof. Demo');
    await page.selectOption('select[name="level"]', 'introductory');
    await page.fill('textarea[name="student_goal"]', 'Prepararme para el parcial y reforzar conceptos semanales.');
    await page.fill('input[name="main_topics_text"]', 'fotosintesis, celula, genetica');
    await wait(800);
    // Scroll al botón y forzar click
    const submitBtn = page.locator('button:has-text("Crear curso")');
    await submitBtn.scrollIntoViewIfNeeded();
    await submitBtn.click({ force: true });
    // Esperar navegación explícita
    try {
      await page.waitForURL(/cursos\/\d+\//, { timeout: 15000 });
    } catch (e) {
      console.log('URL after course create:', page.url());
      await screenshot('03-curso-error');
      throw e;
    }
    await wait(1500);
    await screenshot('03-curso-creado');

    // ========== 3.5 Upgrade usuario a plan básico para poder usar API ==========
    console.log('3.5 Upgrade usuario');
    const upgradeCmd = `python "${path.join(__dirname, 'upgrade_user.py')}" ${USERNAME}`;
    execSync(upgradeCmd, { cwd: path.resolve(__dirname, '..'), stdio: 'inherit' });
    await page.reload({ waitUntil: 'networkidle' });
    await wait(1500);

    // ========== 4. Subir clase con audio ==========
    console.log('4. Subir clase con audio');
    await page.goto(`${BASE_URL}/api/nueva/`, { waitUntil: 'networkidle' });
    await wait(1500);
    await screenshot('04a-formulario-api');

    // Seleccionar curso
    try {
      await page.selectOption('select[name="course"]', { index: 1 });
      await wait(500);
    } catch (e) {
      console.log('No course select or already preselected');
    }

    // Llenar título
    await page.fill('input[name="title"]', 'Clase de Historia del Perú - Demo');
    await page.fill('input[name="tags"]', 'historia, peru, demo');

    // Seleccionar modo audio
    await safeClick('#lbl-mode-audio');
    await wait(1000);

    // Subir archivo
    const fileInput = await page.locator('input[type="file"]').first();
    await fileInput.setInputFiles(AUDIO_PATH);
    await wait(1500);

    // Submit
    await safeClick('#submit-btn');
    await page.waitForSelector('.message, #processing-status, .study-actions-grid, .errorlist', { timeout: 25000 });
    await wait(2500);
    await screenshot('04-clase-subida');

    // ========== 5. Fix lesson vía Python ==========
    console.log('5. Fix lesson');
    const fixCmd = `python "${path.join(__dirname, 'fix_lesson.py')}" ${USERNAME}`;
    execSync(fixCmd, { cwd: path.resolve(__dirname, '..'), stdio: 'inherit' });
    await wait(1500);

    // ========== 6. Ir a dashboard y entrar a la clase ==========
    console.log('6. Entrar a la clase');
    // Leer job_id del archivo escrito por fix_lesson.py
    const jobIdFile = path.join(__dirname, 'job_id.txt');
    let jobId = '';
    if (fs.existsSync(jobIdFile)) {
      jobId = fs.readFileSync(jobIdFile, 'utf8').trim();
    }
    await page.goto(`${BASE_URL}/dashboard/`, { waitUntil: 'networkidle' });
    await wait(1500);
    await screenshot('05a-dashboard-clases');
    // Navegar directamente a la clase
    if (jobId) {
      await page.goto(`${BASE_URL}/clase/${jobId}/`, { waitUntil: 'networkidle' });
    } else {
      const classLink = page.locator('a[href^="/clase/"]').first();
      await classLink.click({ force: true });
      await page.waitForURL('**/clase/**', { timeout: 20000 });
    }
    await wait(2000);
    await screenshot('05-clase-lista');

    // ========== 7. Compartir / Visibilidad ==========
    console.log('7. Compartir / Visibilidad');
    await safeClick('button[title="Compartir / Visibilidad"]');
    await wait(1000);
    await safeClick('.share-option[data-value="public"]');
    await wait(800);
    await safeClick('#share-modal .primary-button:has-text("Guardar")');
    await wait(1500);
    await screenshot('06-visibilidad');

    // ========== 8. Tomar Quiz ==========
    console.log('8. Quiz');
    await safeClick('.study-action-btn--quiz');
    await page.waitForSelector('form[action*="quiz/iniciar/"], .quiz-panel, .quiz-panel--result', { timeout: 15000 });
    await wait(1000);

    // Si estamos en la página de iniciar quiz
    const startForm = await page.locator('form[action*="quiz/iniciar/"]').count();
    if (startForm > 0) {
      await safeClick('button[value="5"], .intensity-btn:has-text("5")');
      await wait(600);
      await safeClick('button[type="submit"]:has-text("Iniciar")');
      await page.waitForURL('**/quiz/**', { timeout: 20000 });
      await wait(1500);
    }
    await screenshot('07-quiz-iniciado');

    // Responder preguntas
    let safety = 0;
    while (safety < 20) {
      safety++;
      const resultPanel = await page.locator('.quiz-panel--result').count();
      if (resultPanel > 0) break;

      const options = await page.locator('.answer-option').all();
      if (options.length > 0) {
        await options[0].click();
        await wait(800);
        await safeClick('button:has-text("Responder y continuar")');
        await wait(1500);
      } else {
        await wait(800);
      }
    }
    await wait(2000);
    await screenshot('08-quiz-resultado');

    // ========== 9. Flashcards ==========
    console.log('9. Flashcards');
    await safeClick('.result-actions .secondary-button:has-text("Repasar"), a:has-text("Repasar flashcards")');
    await page.waitForURL('**/flashcards/**', { timeout: 20000 });
    await wait(2000);
    await screenshot('09-flashcards');

    for (let i = 0; i < 4; i++) {
      await page.evaluate(() => { if (typeof flipCard === 'function') flipCard(document.querySelector('.flashcard-inner')); });
      await wait(1200);
      await page.evaluate(() => { if (typeof rateCard === 'function') rateCard('medium'); });
      await wait(1500);
    }
    await screenshot('10-flashcards-repaso');

    // ========== 10. Mapa de clase ==========
    console.log('10. Mapa');
    await page.goto(page.url().replace('/flashcards/', '/mapa/'), { waitUntil: 'networkidle' });
    await wait(2000);
    await screenshot('11-mapa');

    // ========== 11. Ejercicios ==========
    console.log('11. Ejercicios');
    await page.goto(page.url().replace('/mapa/', '/'), { waitUntil: 'networkidle' });
    await wait(1500);
    await safeClick('.study-action-btn--match');
    await page.waitForURL('**/emparejar/**', { timeout: 20000 });
    await wait(2000);
    await screenshot('12-emparejar');

    await page.goto(page.url().replace('/emparejar/', '/completar/'), { waitUntil: 'networkidle' });
    await wait(2000);
    await screenshot('13-completar');

    // Volver a dashboard final
    console.log('12. Dashboard final');
    await page.goto(`${BASE_URL}/dashboard/`, { waitUntil: 'networkidle' });
    await wait(2000);
    await screenshot('14-dashboard-final');

    console.log('Flujo completado exitosamente');
  } catch (err) {
    console.error('Error fatal en el flujo:', err);
    await screenshot('error');
  } finally {
    await context.close();
    await browser.close();
  }

  // ========== Convertir video a MP4 ==========
  const webmFiles = fs.readdirSync(VIDEO_DIR).filter(f => f.endsWith('.webm'));
  if (webmFiles.length > 0) {
    const webmPath = path.join(VIDEO_DIR, webmFiles[0]);
    const mp4Path = path.join(OUTPUT_DIR, 'demo-presentacion.mp4');
    console.log('Convirtiendo video a MP4...');
    const cmd = `"${ffmpegPath}" -y -i "${webmPath}" -c:v libx264 -preset fast -crf 23 -movflags +faststart -pix_fmt yuv420p "${mp4Path}"`;
    execSync(cmd, { stdio: 'inherit' });
    console.log('MP4 guardado en:', mp4Path);
    fs.unlinkSync(webmPath);
    fs.rmdirSync(VIDEO_DIR);
  } else {
    console.log('No se encontró archivo de video webm');
  }
})();
