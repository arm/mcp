const steps = Array.from(document.querySelectorAll(".step"));
const form = document.getElementById("wizardForm");
const stepLabel = document.getElementById("stepLabel");
const backButton = document.getElementById("backButton");
const nextButton = document.getElementById("nextButton");
const generateButton = document.getElementById("generateButton");
const budgetInput = document.getElementById("questionBudget");
const budgetValue = document.getElementById("questionBudgetValue");
const resultPanel = document.getElementById("resultPanel");
const resultTitle = document.getElementById("resultTitle");
const resultSummary = document.getElementById("resultSummary");
const sectionList = document.getElementById("sectionList");
const jsonPreview = document.getElementById("jsonPreview");
const questionCount = document.getElementById("questionCount");
const suggestedFilename = document.getElementById("suggestedFilename");
const suggestedCommand = document.getElementById("suggestedCommand");
const saveButton = document.getElementById("saveButton");
const saveStatus = document.getElementById("saveStatus");

let currentStep = 0;
let latestPayload = null;

function updateBudgetLabel() {
  budgetValue.textContent = `${budgetInput.value} questions`;
}

function updateWizard() {
  steps.forEach((step, index) => {
    step.classList.toggle("is-active", index === currentStep);
  });
  stepLabel.textContent = `Step ${currentStep + 1} of ${steps.length}`;
  backButton.disabled = currentStep === 0;
  nextButton.hidden = currentStep === steps.length - 1;
  generateButton.hidden = currentStep !== steps.length - 1;
}

function collectFormData() {
  const data = new FormData(form);
  return {
    topic: data.get("topic") || "",
    audience: data.get("audience") || "",
    subtopics: data.get("subtopics") || "",
    known_gaps: data.get("known_gaps") || "",
    keywords: data.get("keywords") || "",
    question_budget: Number(data.get("question_budget") || 20),
    environments: data.getAll("environments"),
    content_types: data.getAll("content_types"),
    goals: data.getAll("goals"),
  };
}

function renderSections(questions) {
  sectionList.innerHTML = "";
  Object.entries(questions).forEach(([section, items]) => {
    const card = document.createElement("article");
    card.className = "section-card";

    const title = document.createElement("h4");
    title.textContent = section.replaceAll("_", " ");
    card.appendChild(title);

    const list = document.createElement("ul");
    items.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      list.appendChild(li);
    });
    card.appendChild(list);
    sectionList.appendChild(card);
  });
}

async function generateQuestions(event) {
  event.preventDefault();
  saveStatus.textContent = "";

  const payload = collectFormData();
  const response = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();

  if (!response.ok) {
    saveStatus.textContent = result.error || "Unable to generate questions.";
    saveStatus.className = "save-status is-error";
    return;
  }

  latestPayload = payload;
  resultPanel.classList.remove("is-hidden");
  resultTitle.textContent = result.title;
  resultSummary.innerHTML = result.summary;
  questionCount.textContent = result.question_count;
  suggestedFilename.textContent = result.suggested_filename;
  suggestedCommand.textContent = result.suggested_command;
  jsonPreview.textContent = JSON.stringify(result.questions, null, 2);
  renderSections(result.questions);
  resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function saveQuestions() {
  if (!latestPayload) {
    return;
  }

  saveStatus.textContent = "Saving JSON...";
  saveStatus.className = "save-status";

  const response = await fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(latestPayload),
  });
  const result = await response.json();

  if (!response.ok) {
    saveStatus.textContent = result.error || "Unable to save the generated JSON.";
    saveStatus.className = "save-status is-error";
    return;
  }

  saveStatus.textContent = `Saved ${result.question_count} questions to ${result.path}`;
  saveStatus.className = "save-status is-success";
  suggestedCommand.textContent = result.suggested_command;
}

backButton.addEventListener("click", () => {
  if (currentStep > 0) {
    currentStep -= 1;
    updateWizard();
  }
});

nextButton.addEventListener("click", () => {
  if (currentStep < steps.length - 1) {
    currentStep += 1;
    updateWizard();
  }
});

budgetInput.addEventListener("input", updateBudgetLabel);
form.addEventListener("submit", generateQuestions);
saveButton.addEventListener("click", saveQuestions);

updateBudgetLabel();
updateWizard();
