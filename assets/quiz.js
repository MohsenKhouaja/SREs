document.querySelectorAll("[data-quiz]").forEach((quiz) => {
  const button = quiz.querySelector("button");
  const feedback = quiz.querySelector("[data-feedback]");

  button?.addEventListener("click", () => {
    const selected = quiz.querySelector('input[type="radio"]:checked');
    if (!selected) {
      feedback.textContent = "Choose one answer before checking.";
      feedback.className = "quiz-feedback incorrect";
      return;
    }

    const correct = selected.value === quiz.dataset.answer;
    feedback.textContent = correct
      ? `Correct. ${quiz.dataset.correct}`
      : `Not yet. ${quiz.dataset.incorrect}`;
    feedback.className = `quiz-feedback ${correct ? "correct" : "incorrect"}`;
  });
});
