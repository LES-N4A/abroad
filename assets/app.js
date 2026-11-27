/* Abroad — shared UI behaviour */
(function () {
    'use strict';

    /* ------------------------------------------------------------------
       Toast helper
       ------------------------------------------------------------------ */
    function toast(message, type) {
        var element = document.getElementById('flash-toast');
        if (!element) {
            element = document.createElement('div');
            element.className = 'notification';
            element.id = 'flash-toast';
            element.setAttribute('role', 'status');
            document.body.appendChild(element);
        }
        element.textContent = message;
        element.className = 'notification ' + (type || 'info');
        element.style.display = 'block';
        window.clearTimeout(window.__abroadToast);
        window.__abroadToast = window.setTimeout(function () {
            element.style.display = 'none';
        }, 4200);
    }

    var flash = document.getElementById('flash-toast');
    if (flash) {
        window.setTimeout(function () { flash.style.display = 'none'; }, 4600);
        flash.addEventListener('click', function () { flash.style.display = 'none'; });
    }

    document.querySelectorAll('.notification-stack .notification').forEach(function (item) {
        window.setTimeout(function () { item.style.display = 'none'; }, 5200);
        item.addEventListener('click', function () { item.style.display = 'none'; });
    });

    /* ------------------------------------------------------------------
       Mobile navigation
       ------------------------------------------------------------------ */
    var toggle = document.querySelector('[data-nav-toggle]');
    var mobileNav = document.querySelector('[data-mobile-nav]');

    function setNav(open) {
        if (!mobileNav || !toggle) return;
        mobileNav.classList.toggle('is-open', open);
        toggle.classList.toggle('is-open', open);
        toggle.setAttribute('aria-expanded', String(open));
        toggle.innerHTML = open
            ? '<i class="fas fa-xmark"></i>'
            : '<i class="fas fa-bars"></i>';
    }

    if (toggle && mobileNav) {
        toggle.addEventListener('click', function (event) {
            event.stopPropagation();
            setNav(!mobileNav.classList.contains('is-open'));
        });

        mobileNav.addEventListener('click', function (event) {
            if (event.target.closest('a')) setNav(false);
        });

        document.addEventListener('click', function (event) {
            if (!mobileNav.classList.contains('is-open')) return;
            if (event.target.closest('[data-mobile-nav]') || event.target.closest('[data-nav-toggle]')) return;
            setNav(false);
        });
    }

    /* ------------------------------------------------------------------
       Account menu
       ------------------------------------------------------------------ */
    var userToggle = document.querySelector('[data-user-menu-toggle]');
    var userMenu = document.querySelector('[data-user-menu]');

    function setUserMenu(open) {
        if (!userMenu) return;
        userMenu.classList.toggle('show', open);
    }

    if (userToggle && userMenu) {
        userToggle.addEventListener('click', function (event) {
            event.stopPropagation();
            setUserMenu(!userMenu.classList.contains('show'));
        });

        userToggle.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                setUserMenu(!userMenu.classList.contains('show'));
            }
        });

        document.addEventListener('click', function (event) {
            if (!userMenu.classList.contains('show')) return;
            if (event.target.closest('[data-user-menu]')) return;
            setUserMenu(false);
        });
    }

    /* ------------------------------------------------------------------
       Modals
       ------------------------------------------------------------------ */
    function openModal(id) {
        var modal = document.getElementById(id);
        if (!modal) return;
        modal.classList.add('show');
        document.body.style.overflow = 'hidden';
        var focusable = modal.querySelector('input:not([type="hidden"]), select, textarea, button');
        if (focusable) window.setTimeout(function () { focusable.focus(); }, 60);
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.classList.remove('show');
        if (!document.querySelector('.modal.show')) document.body.style.overflow = '';
    }

    document.addEventListener('click', function (event) {
        var opener = event.target.closest('[data-open-modal]');
        if (opener) {
            event.preventDefault();
            openModal(opener.getAttribute('data-open-modal'));
            return;
        }

        var closer = event.target.closest('[data-close-modal]');
        if (closer) {
            event.preventDefault();
            closeModal(closer.closest('.modal'));
            return;
        }

        if (event.target.classList.contains('modal')) {
            closeModal(event.target);
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var open = document.querySelector('.modal.show');
        if (open) {
            closeModal(open);
            return;
        }
        setNav(false);
        setUserMenu(false);
    });

    /* ------------------------------------------------------------------
       Copy to clipboard
       ------------------------------------------------------------------ */
    document.addEventListener('click', function (event) {
        var button = event.target.closest('[data-copy]');
        if (!button) return;
        var value = button.getAttribute('data-copy');
        if (!value) return;

        function done() {
            var original = button.innerHTML;
            button.innerHTML = '<i class="fas fa-check"></i> Copied';
            toast('Copied to clipboard.', 'success');
            window.setTimeout(function () { button.innerHTML = original; }, 1800);
        }

        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(value).then(done).catch(function () {
                toast('Copy failed — select the code manually.', 'error');
            });
        } else {
            var helper = document.createElement('textarea');
            helper.value = value;
            helper.style.position = 'fixed';
            helper.style.opacity = '0';
            document.body.appendChild(helper);
            helper.select();
            try {
                document.execCommand('copy');
                done();
            } catch (error) {
                toast('Copy failed — select the code manually.', 'error');
            }
            document.body.removeChild(helper);
        }
    });

    /* ------------------------------------------------------------------
       Confirm destructive forms
       ------------------------------------------------------------------ */
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
        form.addEventListener('submit', function (event) {
            if (!window.confirm(form.getAttribute('data-confirm'))) {
                event.preventDefault();
            }
        });
    });

    /* ------------------------------------------------------------------
       Product file input hint
       ------------------------------------------------------------------ */
    document.querySelectorAll('input[type="file"]').forEach(function (input) {
        input.addEventListener('change', function () {
            var file = input.files && input.files[0];
            if (!file) return;
            var label = input.parentElement.querySelector('small');
            if (label) label.textContent = file.name + ' · ' + Math.round(file.size / 1024) + ' KB';
        });
    });
})();
