const technicalToggle = document.getElementById("technicalToggle");
const technicalDetails = document.getElementById("technicalDetails");
const arrow = document.getElementById("arrow");

technicalToggle.addEventListener("click", () => {
    technicalDetails.classList.toggle("show");
    arrow.classList.toggle("open");
});


// Create form button
const createButton = document.getElementById("createButton");

createButton.addEventListener("click", () => {
    // Change this to whatever URL you want.
    window.location.href = "#";
});