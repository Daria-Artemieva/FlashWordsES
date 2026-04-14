const form = document.getElementById("word-form");
const spanishInput = document.getElementById("spanish");
const translationInput = document.getElementById("translation");
const targetLanguageSelect = document.getElementById("target-language");
const messageBox = document.getElementById("message-box");
const wordList = document.getElementById("word-list");
const wordCount = document.getElementById("word-count");
const toggleWordListButton = document.getElementById("toggle-word-list");
const flashcard = document.getElementById("flashcard");
const flashcardFrontText = document.getElementById("flashcard-front-text");
const flashcardBackText = document.getElementById("flashcard-back-text");
const nextCardButton = document.getElementById("next-card");

const startTestButton = document.getElementById("start-test");
const testPrompt = document.getElementById("test-prompt");
const testSpanishWord = document.getElementById("test-spanish-word");
const testForm = document.getElementById("test-form");
const testTranslationInput = document.getElementById("test-translation");
const testSubmitButton = document.getElementById("submit-test");
const testResult = document.getElementById("test-result");
const testSummary = document.getElementById("test-summary");
const retryTestButton = document.getElementById("retry-test");

let words = [];
let currentCardIndex = 0;
let isCardFlipped = false;
let isWordListExpanded = false;
let messageTimeoutId = null;

let testWords = [];
let testIndex = 0;
let testCorrect = 0;
let testIncorrect = 0;
let testAdvanceTimeoutId = null;

function updateControls() {
  const hasWords = words.length > 0;
  nextCardButton.disabled = !hasWords;
  startTestButton.disabled = !hasWords;
}

function showMessage(text, type, options = {}) {
  const { autoHideMs = null } = options;

  if (messageTimeoutId !== null) {
    clearTimeout(messageTimeoutId);
    messageTimeoutId = null;
  }

  messageBox.textContent = text;
  messageBox.className = `message-box ${type}`;

  if (typeof autoHideMs === "number" && autoHideMs > 0) {
    messageTimeoutId = setTimeout(() => {
      clearMessage();
    }, autoHideMs);
  }
}

function clearMessage() {
  if (messageTimeoutId !== null) {
    clearTimeout(messageTimeoutId);
    messageTimeoutId = null;
  }

  messageBox.textContent = "";
  messageBox.className = "message-box hidden";
}

function containsDigits(text) {
  return /\d/.test(text);
}

async function fetchWords() {
  const response = await fetch("/words");
  if (!response.ok) {
    throw new Error("Failed to load words");
  }
  const data = await response.json();
  return Array.isArray(data) ? data : [];
}

async function loadWords() {
  try {
    words = await fetchWords();
    renderWordList();
    updateFlashcard();
    updateControls();
  } catch (error) {
    console.error("Failed to load words:", error);
  }
}

async function addWord(spanish, translation, targetLanguage) {
  try {
    const response = await fetch("/words", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        spanish,
        translation,
        target_language: targetLanguage,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || "Failed to add word");
    }

    const newWord = await response.json();
    words.push(newWord);
    currentCardIndex = words.length - 1;
    isCardFlipped = false;
    renderWordList();
    updateFlashcard();
    updateControls();
    showMessage("Word added successfully.", "success", { autoHideMs: 2500 });
    return true;
  } catch (error) {
    console.error("Failed to add word:", error);
    showMessage(error.message, "error", { autoHideMs: 6000 });
    return false;
  }
}

async function deleteWord(wordId) {
  try {
    const response = await fetch(`/words/${wordId}`, {
      method: "DELETE",
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || "Failed to delete word");
    }

    words = words.filter((word) => word.id !== wordId);

    if (currentCardIndex >= words.length) {
      currentCardIndex = 0;
    }

    isCardFlipped = false;
    renderWordList();
    updateFlashcard();
    updateControls();
    showMessage("Word deleted successfully.", "success", { autoHideMs: 2500 });
  } catch (error) {
    console.error("Failed to delete word:", error);
    showMessage(error.message, "error", { autoHideMs: 6000 });
  }
}

function renderWordList() {
  wordList.innerHTML = "";
  wordCount.textContent = `${words.length} word${words.length === 1 ? "" : "s"}`;
  toggleWordListButton.classList.toggle("hidden", words.length <= 5);
  toggleWordListButton.textContent = isWordListExpanded ? "Show less" : "Show all";

  if (words.length === 0) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-state";
    emptyItem.textContent = "No words yet.";
    wordList.appendChild(emptyItem);
    return;
  }

  const orderedWords = [...words].reverse();
  const visibleWords = isWordListExpanded ? orderedWords : orderedWords.slice(0, 5);

  visibleWords.forEach((word) => {
    const listItem = document.createElement("li");
    listItem.className = "word-item";

    const text = document.createElement("span");
    text.className = "word-text";
    text.textContent = `${word.spanish} - ${word.translation}`;

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "delete-button";
    deleteButton.textContent = "Delete";
    deleteButton.addEventListener("click", () => deleteWord(word.id));

    listItem.appendChild(text);
    listItem.appendChild(deleteButton);
    wordList.appendChild(listItem);
  });
}

function updateFlashcard() {
  flashcard.classList.remove("is-flipped");

  if (words.length === 0) {
    flashcardFrontText.textContent = "Add a word to begin";
    flashcardBackText.textContent = "Translation will appear here";
    return;
  }

  const currentWord = words[currentCardIndex];
  flashcardFrontText.textContent = currentWord.spanish;
  flashcardBackText.textContent = currentWord.translation;

  if (isCardFlipped) {
    flashcard.classList.add("is-flipped");
  }
}

function showNextCard() {
  if (words.length === 0) {
    return;
  }

  currentCardIndex = (currentCardIndex + 1) % words.length;
  isCardFlipped = false;
  updateFlashcard();
}

function toggleWordList() {
  isWordListExpanded = !isWordListExpanded;
  renderWordList();
}

function normalizeAnswer(text) {
  return String(text || "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
}

function shuffleInPlace(items) {
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}

function setHidden(element, isHidden) {
  element.classList.toggle("hidden", isHidden);
}

function clearTestAdvanceTimeout() {
  if (testAdvanceTimeoutId !== null) {
    clearTimeout(testAdvanceTimeoutId);
    testAdvanceTimeoutId = null;
  }
}

function showTestResult(text, kind) {
  testResult.textContent = text;
  testResult.className = `test-result ${kind}`;
}

function clearTestResult() {
  testResult.textContent = "";
  testResult.className = "test-result hidden";
}

function renderCurrentTestWord() {
  clearTestAdvanceTimeout();
  clearTestResult();

  if (testIndex >= testWords.length) {
    finishTest();
    return;
  }

  const current = testWords[testIndex];
  testSpanishWord.textContent = current.spanish;
  testTranslationInput.value = "";
  testTranslationInput.focus();
}

function finishTest() {
  clearTestAdvanceTimeout();
  setHidden(testPrompt, true);

  const total = testWords.length;
  const percent = total === 0 ? 0 : testCorrect / total;
  const headline = percent < 0.5 ? "You should repeat this test" : "Good job!";

  testSummary.textContent = `${headline}\n\nTotal words: ${total}\nCorrect: ${testCorrect}\nIncorrect: ${testIncorrect}`;
  setHidden(testSummary, false);

  setHidden(retryTestButton, percent < 0.5);
  startTestButton.disabled = false;
}

async function startTest() {
  clearTestAdvanceTimeout();
  clearTestResult();
  setHidden(testSummary, true);
  setHidden(retryTestButton, true);

  startTestButton.disabled = true;

  try {
    words = await fetchWords();
    renderWordList();
    updateFlashcard();
  } catch (error) {
    console.error("Failed to start test:", error);
    showTestResult("Failed to load words for test.", "incorrect");
    startTestButton.disabled = false;
    return;
  }

  if (words.length === 0) {
    showTestResult("No words to test. Add some words first.", "incorrect");
    startTestButton.disabled = false;
    return;
  }

  testWords = shuffleInPlace([...words]);
  testIndex = 0;
  testCorrect = 0;
  testIncorrect = 0;

  setHidden(testPrompt, false);
  renderCurrentTestWord();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const spanish = spanishInput.value.trim();
  const translation = translationInput.value.trim();
  const targetLanguage = targetLanguageSelect.value;

  if (!spanish) {
    showMessage("Spanish word is required.", "error");
    return;
  }

  if (containsDigits(spanish)) {
    showMessage("Spanish word cannot contain numbers.", "error");
    return;
  }

  if (translation && containsDigits(translation)) {
    showMessage("Translation cannot contain numbers.", "error");
    return;
  }

  clearMessage();
  const wasAdded = await addWord(spanish, translation, targetLanguage);

  if (wasAdded) {
    form.reset();
    targetLanguageSelect.value = targetLanguage;
    spanishInput.focus();
  }
});

function clearMessageOnInput() {
  if (messageBox.classList.contains("hidden")) {
    return;
  }
  clearMessage();
}

spanishInput.addEventListener("input", clearMessageOnInput);
translationInput.addEventListener("input", clearMessageOnInput);
targetLanguageSelect.addEventListener("change", clearMessageOnInput);

startTestButton.addEventListener("click", startTest);
retryTestButton.addEventListener("click", startTest);

testTranslationInput.addEventListener("input", () => {
  if (!testResult.classList.contains("hidden")) {
    clearTestResult();
  }
});

testForm.addEventListener("submit", (event) => {
  event.preventDefault();

  if (testIndex >= testWords.length) {
    return;
  }

  const current = testWords[testIndex];
  const expected = normalizeAnswer(current.translation);
  const actual = normalizeAnswer(testTranslationInput.value);

  if (actual && actual === expected) {
    testCorrect += 1;
    showTestResult("Correct", "correct");
  } else {
    testIncorrect += 1;
    showTestResult(`Incorrect. Correct answer: ${current.translation}`, "incorrect");
  }

  testIndex += 1;
  testSubmitButton.disabled = true;

  clearTestAdvanceTimeout();
  testAdvanceTimeoutId = setTimeout(() => {
    testSubmitButton.disabled = false;
    renderCurrentTestWord();
  }, 900);
});

flashcard.addEventListener("click", () => {
  if (words.length === 0) {
    return;
  }

  isCardFlipped = !isCardFlipped;
  flashcard.classList.toggle("is-flipped", isCardFlipped);
});

flashcard.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    flashcard.click();
  }
});

nextCardButton.addEventListener("click", showNextCard);
toggleWordListButton.addEventListener("click", toggleWordList);

loadWords();
updateControls();
