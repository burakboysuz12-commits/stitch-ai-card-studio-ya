/* Görev Defteri — başlık + açıklama + görsel destekli frontend mantığı */

const taskForm = document.getElementById("taskForm");
const taskInput = document.getElementById("taskInput");
const submitBtn = document.getElementById("submitBtn");

const taskDesc = document.getElementById("taskDesc");
const descToggle = document.getElementById("descToggle");
const descPanel = document.getElementById("descPanel");
const descCount = document.getElementById("descCount");

const imgToggle = document.getElementById("imgToggle");
const imgPanel = document.getElementById("imgPanel");
const imgInput = document.getElementById("imgInput");
const dropzone = document.getElementById("dropzone");
const imgPreview = document.getElementById("imgPreview");
const imgPreviewTag = document.getElementById("imgPreviewTag");
const imgPreviewName = document.getElementById("imgPreviewName");
const imgRemove = document.getElementById("imgRemove");

const taskList = document.getElementById("taskList");
const emptyState = document.getElementById("emptyState");
const clearBtn = document.getElementById("clearCompleted");
const progressText = document.getElementById("progressText");
const progressPercent = document.getElementById("progressPercent");
const progressFill = document.getElementById("progressFill");
const dateLine = document.getElementById("dateLine");

const lightbox = document.getElementById("lightbox");
const lightboxImg = document.getElementById("lightboxImg");
const lightboxClose = document.getElementById("lightboxClose");
const toastEl = document.getElementById("toast");

const MAX_DESC = 1000;
const MAX_UPLOAD = 8 * 1024 * 1024;

let tasks = [];
let currentFilter = "all";
let editingId = null;          // şu an düzenlenen görev id'si
let expandedIds = new Set();   // açıklaması tam açılan görevler
let pendingImage = "";         // forma seçilen görselin URL'si
let toastTimer = null;

/* ---------------- Tarih / saat ---------------- */
dateLine.textContent = new Date().toLocaleDateString("tr-TR", {
  weekday: "long", day: "numeric", month: "long", year: "numeric",
});

/* ---------------- Yardımcılar ---------------- */
function toast(message, isError = false) {
  toastEl.textContent = message;
  toastEl.classList.toggle("error", isError);
  toastEl.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.add("hidden"), 3200);
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Bir şeyler ters gitti.");
  return data;
}

/* ---------------- Veri ---------------- */
async function fetchTasks() {
  tasks = await api("/api/tasks");
  render();
}

async function addTask(title, description, image) {
  const task = await api("/api/tasks", {
    method: "POST",
    body: JSON.stringify({ title, description, image }),
  });
  tasks.push(task);
  render();
}

async function patchTask(id, changes) {
  const updated = await api(`/api/tasks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
  const i = tasks.findIndex(t => t.id === id);
  if (i !== -1) tasks[i] = updated;
  render();
}

async function removeTask(id) {
  await api(`/api/tasks/${id}`, { method: "DELETE" });
  tasks = tasks.filter(t => t.id !== id);
  if (editingId === id) cancelEditing();
  render();
}

/* ---------------- Görsel yükleme ---------------- */
async function uploadImage(file) {
  if (!file.type.startsWith("image/")) {
    toast("Yalnızca görsel dosyası yükleyebilirsin.", true);
    return;
  }
  if (file.size > MAX_UPLOAD) {
    toast("Görsel 8 MB'tan büyük olamaz.", true);
    return;
  }
  dropzone.classList.add("uploading");
  dropzone.querySelector(".dz-text").textContent = "Yükleniyor...";

  const form = new FormData();
  form.append("file", file);

  try {
    const res = await fetch("/api/upload", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Görsel yüklenemedi.");
    pendingImage = data.url;
    showPreview(data.url, file.name);
    toast("Görsel eklendi 🖼️");
  } catch (err) {
    toast(err.message, true);
  } finally {
    dropzone.classList.remove("uploading");
    dropzone.querySelector(".dz-text").innerHTML = 'Dosya seç <em>veya buraya sürükle</em>';
    imgInput.value = "";
  }
}

function showPreview(url, name = "") {
  imgPreviewTag.src = url;
  imgPreviewName.textContent = name || url.split("/").pop();
  imgPreview.classList.remove("hidden");
  dropzone.classList.add("hidden");
}

function clearImagePicker() {
  pendingImage = "";
  imgPreview.classList.add("hidden");
  dropzone.classList.remove("hidden");
  imgInput.value = "";
}

imgToggle.addEventListener("click", () => togglePanel(imgToggle, imgPanel));
imgInput.addEventListener("change", e => {
  if (e.target.files[0]) uploadImage(e.target.files[0]);
});
imgRemove.addEventListener("click", () => {
  clearImagePicker();
  if (editingId) patchTask(editingId, { image: "" });
});

["dragenter", "dragover"].forEach(ev =>
  dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.add("drag"); }));
["dragleave", "drop"].forEach(ev =>
  dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.remove("drag"); }));
dropzone.addEventListener("drop", e => {
  const file = e.dataTransfer.files[0];
  if (file) uploadImage(file);
});

/* ---------------- Panel aç/kapat ---------------- */
function togglePanel(btn, panel) {
  const open = panel.classList.toggle("hidden") === false;
  btn.classList.toggle("open", open);
  btn.querySelector(".chev").style.transform = open ? "rotate(90deg)" : "";
  return open;
}

descToggle.addEventListener("click", () => {
  if (togglePanel(descToggle, descPanel)) taskDesc.focus();
});

taskDesc.addEventListener("input", () => {
  descCount.textContent = `${taskDesc.value.length} / ${MAX_DESC}`;
});

/* ---------------- Form ---------------- */
taskForm.addEventListener("submit", async e => {
  e.preventDefault();
  const title = taskInput.value.trim();
  if (!title) {
    toast("Önce bir görev başlığı yaz.", true);
    taskInput.focus();
    return;
  }
  submitBtn.disabled = true;
  try {
    if (editingId) {
      await patchTask(editingId, {
        title,
        description: taskDesc.value.trim(),
        image: pendingImage,
      });
      toast("Görev güncellendi ✅");
      cancelEditing();
    } else {
      await addTask(title, taskDesc.value.trim(), pendingImage);
      resetForm();
    }
  } catch (err) {
    toast(err.message, true);
  } finally {
    submitBtn.disabled = false;
    taskInput.focus();
  }
});

function resetForm() {
  taskInput.value = "";
  taskDesc.value = "";
  descCount.textContent = `0 / ${MAX_DESC}`;
  clearImagePicker();
  descPanel.classList.add("hidden");
  descToggle.classList.remove("open");
  descToggle.querySelector(".chev").style.transform = "";
  imgPanel.classList.add("hidden");
  imgToggle.classList.remove("open");
  imgToggle.querySelector(".chev").style.transform = "";
}

function startEditing(task) {
  editingId = task.id;
  taskInput.value = task.title;
  taskDesc.value = task.description || "";
  descCount.textContent = `${(task.description || "").length} / ${MAX_DESC}`;
  pendingImage = task.image || "";
  if (pendingImage) {
    showPreview(pendingImage);
    imgPanel.classList.remove("hidden");
    imgToggle.classList.add("open");
    imgToggle.querySelector(".chev").style.transform = "rotate(90deg)";
  } else {
    clearImagePicker();
  }
  submitBtn.textContent = "Kaydet";
  taskForm.scrollIntoView({ behavior: "smooth", block: "center" });
  taskInput.focus();
}

function cancelEditing() {
  editingId = null;
  submitBtn.textContent = "Ekle";
  resetForm();
}

/* ---------------- Filtreler ---------------- */
document.querySelectorAll(".filter-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.filter;
    render();
  });
});

clearBtn.addEventListener("click", async () => {
  if (!tasks.some(t => t.done)) return toast("Temizlenecek tamamlanan görev yok.");
  await api("/api/completed", { method: "DELETE" });
  await fetchTasks();
  toast("Tamamlananlar temizlendi 🧹");
});

/* ---------------- Lightbox ---------------- */
function openLightbox(url) {
  lightboxImg.src = url;
  lightbox.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}
function closeLightbox() {
  lightbox.classList.add("hidden");
  lightboxImg.src = "";
  document.body.style.overflow = "";
}
lightboxClose.addEventListener("click", closeLightbox);
lightbox.addEventListener("click", e => { if (e.target === lightbox) closeLightbox(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeLightbox(); });

/* ---------------- Çizim ---------------- */
function render() {
  const visible = tasks.filter(t =>
    currentFilter === "all" ? true :
    currentFilter === "active" ? !t.done : t.done);

  taskList.innerHTML = "";
  visible.forEach(t => taskList.appendChild(buildCard(t)));

  emptyState.classList.toggle("hidden", visible.length > 0);
  emptyState.textContent = tasks.length === 0
    ? "Henüz görev yok. Yukarıdan ilk görevini ekle ✨"
    : "Bu filtrede gösterilecek görev yok.";

  const total = tasks.length;
  const done = tasks.filter(t => t.done).length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  progressText.textContent = `${done} / ${total} görev tamamlandı`;
  progressPercent.textContent = `%${pct}`;
  progressFill.style.width = `${pct}%`;
  clearBtn.classList.toggle("invisible", done === 0);
}

function buildCard(t) {
  const card = document.createElement("article");
  card.className = "task-card" + (t.done ? " done" : "");

  /* Tamamlama kutusu */
  const check = document.createElement("button");
  check.className = "check";
  check.title = t.done ? "Tamamlanmadı olarak işaretle" : "Tamamlandı olarak işaretle";
  check.innerHTML = t.done ? "✓" : "";
  check.addEventListener("click", () => patchTask(t.id, { done: !t.done }));

  /* İçerik */
  const body = document.createElement("div");
  body.className = "task-body";

  const title = document.createElement("h3");
  title.className = "task-title";
  title.textContent = t.title;
  body.appendChild(title);

  if (t.description) {
    const desc = document.createElement("p");
    const expanded = expandedIds.has(t.id);
    desc.className = "task-desc" + (expanded ? "" : " clamped");
    desc.textContent = t.description;
    desc.title = "Tıklayıp aç/kapat";
    desc.addEventListener("click", () => {
      expandedIds.has(t.id) ? expandedIds.delete(t.id) : expandedIds.add(t.id);
      render();
    });
    body.appendChild(desc);
  }

  if (t.image) {
    const figure = document.createElement("figure");
    figure.className = "task-figure";
    const img = document.createElement("img");
    img.src = t.image;
    img.alt = `${t.title} görseli`;
    img.loading = "lazy";
    img.addEventListener("click", () => openLightbox(t.image));
    img.addEventListener("error", () => { figure.remove(); });
    const cap = document.createElement("figcaption");
    cap.textContent = "🔍 Büyütmek için görseline tıkla";
    figure.append(img, cap);
    body.appendChild(figure);
  }

  const meta = document.createElement("span");
  meta.className = "task-meta";
  meta.textContent = new Date(t.created_at).toLocaleString("tr-TR", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
  body.appendChild(meta);

  /* Eylemler */
  const actions = document.createElement("div");
  actions.className = "task-actions";

  const editBtn = document.createElement("button");
  editBtn.className = "icon-btn";
  editBtn.title = "Düzenle (başlık, açıklama, görsel)";
  editBtn.textContent = "✏️";
  editBtn.addEventListener("click", () => startEditing(t));

  const delBtn = document.createElement("button");
  delBtn.className = "icon-btn danger";
  delBtn.title = "Sil";
  delBtn.textContent = "🗑️";
  delBtn.addEventListener("click", () => removeTask(t.id));

  actions.append(editBtn, delBtn);
  card.append(check, body, actions);
  return card;
}

/* ---------------- Başlat ---------------- */
fetchTasks().catch(err => toast(err.message, true));
