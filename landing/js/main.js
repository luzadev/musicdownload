/* ======================================================
   MusicTools landing — JS minimale
   ====================================================== */

// Anno corrente in footer
(function setYear() {
  const el = document.getElementById("year");
  if (el) el.textContent = String(new Date().getFullYear());
})();

// Lemon Squeezy overlay
// Lo script di Lemon (lemon.js) intercetta automaticamente i link con
// data-lemonsqueezy-url e apre l'overlay. Qui ci limitiamo a impedire
// che il click navighi via se l'URL non e' ancora stato configurato.
document.querySelectorAll("[data-lemonsqueezy-url]").forEach((el) => {
  el.addEventListener("click", (e) => {
    const url = el.getAttribute("data-lemonsqueezy-url");
    if (!url || url === "REPLACE_WITH_LS_PRODUCT_URL") {
      e.preventDefault();
      alert(
        "Il prodotto Lemon Squeezy non e' ancora configurato.\n" +
        "Crea il prodotto su Lemon Squeezy e incolla l'URL dentro " +
        "landing/index.html in data-lemonsqueezy-url."
      );
    }
    // Se la pagina e' aperta via file:// lemon.js non riesce a inizializzare:
    // in quel caso lasciamo che il link navighi via.
  });
});

// Header che diventa piu' opaco mentre scorri (effetto subtle)
const nav = document.querySelector(".nav");
function onScroll() {
  if (!nav) return;
  if (window.scrollY > 24) nav.classList.add("scrolled");
  else nav.classList.remove("scrolled");
}
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

// Reveal on scroll: aggiunge la classe .in-view alle sezioni
// quando entrano in viewport. Niente librerie esterne.
const io = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      entry.target.classList.add("in-view");
      io.unobserve(entry.target);
    }
  });
}, { threshold: 0.12 });

document.querySelectorAll(".feat, .how-step, .price-card, .faq-item").forEach((el) => {
  io.observe(el);
});
