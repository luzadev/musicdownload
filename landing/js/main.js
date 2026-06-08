/* ======================================================
   MusicTools landing — JS minimale
   ====================================================== */

// Anno corrente in footer
(function setYear() {
  const el = document.getElementById("year");
  if (el) el.textContent = String(new Date().getFullYear());
})();

// Lemon Squeezy overlay: lemon.js intercetta automaticamente i link con
// data-lemonsqueezy-url e apre l'overlay di checkout. Niente codice nostro
// necessario qui — basta che lemon.js sia caricato (vedi <script> in index.html).

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
