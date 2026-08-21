const progressInputs = [...document.querySelectorAll("[data-progress]")];
const summary = document.querySelector("[data-progress-summary]");

function renderProgress() {
  const completed = progressInputs.filter((input) => input.checked).length;
  if (summary) summary.textContent = `${completed} of ${progressInputs.length} lessons marked complete`;
}

progressInputs.forEach((input) => {
  const key = `sres-course:${input.dataset.progress}`;
  input.checked = localStorage.getItem(key) === "complete";
  input.addEventListener("change", () => {
    if (input.checked) localStorage.setItem(key, "complete");
    else localStorage.removeItem(key);
    renderProgress();
  });
});

renderProgress();
