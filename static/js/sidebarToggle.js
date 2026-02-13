document.addEventListener("DOMContentLoaded", function () {

    const body = document.body;
    const sidebar = document.getElementById("navBar");
    const toggle = document.querySelector(".sidebar-toggle");

    if (!sidebar || !toggle) return;

    const savedStatus = localStorage.getItem("status");
    if (savedStatus === "close") {
        sidebar.classList.add("close");
        body.classList.add("sidebar-closed");
    }

    toggle.addEventListener("click", function () {
        sidebar.classList.toggle("close");
        body.classList.toggle("sidebar-closed");

        localStorage.setItem(
            "status",
            sidebar.classList.contains("close") ? "close" : "open"
        );
    });

});
