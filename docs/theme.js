/* ELAN Factory — theme controller
 * Применяет data-theme на <html> до рендера (чтобы не мигало).
 * Сам монтирует плавающий переключатель N · P · A в правом верхнем углу.
 * 3 темы: noir (dark) / porcelain (light tiffany) / atelier (editorial luxury)
 */
(function () {
  var KEY = 'elan-theme';
  var THEMES = ['porcelain', 'noir', 'atelier'];
  var DEFAULT = 'porcelain';

  function get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function save(t) { try { localStorage.setItem(KEY, t); } catch (e) {} }

  function apply(t) {
    if (THEMES.indexOf(t) < 0) t = DEFAULT;
    document.documentElement.dataset.theme = t;
    var btns = document.querySelectorAll('.theme-switcher button');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('active', btns[i].dataset.theme === t);
    }
  }

  function set(t) {
    save(t);
    // Reload so charts re-read CSS vars and render in new palette
    window.location.reload();
  }

  // Apply as early as possible (script is in <head>, runs before body)
  var initial = get() || DEFAULT;
  if (THEMES.indexOf(initial) < 0) initial = DEFAULT;
  document.documentElement.dataset.theme = initial;

  window.ElanTheme = { get: get, set: set, apply: apply, themes: THEMES };

  function mount() {
    if (document.querySelector('.theme-switcher')) return;

    var box = document.createElement('div');
    box.className = 'theme-switcher';
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', 'Переключить тему');
    box.innerHTML =
      '<button type="button" data-theme="porcelain" title="Porcelain · светлый Tiffany">P</button>' +
      '<button type="button" data-theme="noir"      title="Noir · сдержанный тёмный">N</button>' +
      '<button type="button" data-theme="atelier"   title="Atelier · editorial luxury">A</button>';

    var btns = box.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function (e) {
        set(e.currentTarget.dataset.theme);
      });
    }
    document.body.appendChild(box);
    apply(initial);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
