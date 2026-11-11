/**
 * Browser Web Push & Desktop Notification Utility for TransM Studio
 */

// Play a pleasant melodic chime using Web Audio API (no external mp3 file required)
export function playCompletionChime() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const now = ctx.currentTime;

    // First note: E5 (659.25 Hz)
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(659.25, now);
    gain1.gain.setValueAtTime(0.12, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.3);

    // Second note: G5 (783.99 Hz)
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(783.99, now + 0.12);
    gain2.gain.setValueAtTime(0.15, now + 0.12);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.12);
    osc2.stop(now + 0.6);
  } catch (_) {
    // AudioContext may be restricted until user gesture; ignore safely
  }
}

/**
 * Checks if user enabled notifications in app settings (stored in localStorage)
 */
export function isNotificationEnabled() {
  if (typeof window === 'undefined') return false;
  const stored = localStorage.getItem('transm_push_enabled');
  if (stored === 'false') return false;
  return true; // Default enabled
}

/**
 * Updates notification enabled preference in localStorage and dispatches change event
 */
export function setNotificationEnabled(enabled) {
  if (typeof window === 'undefined') return;
  localStorage.setItem('transm_push_enabled', enabled ? 'true' : 'false');
  window.dispatchEvent(
    new CustomEvent('transm_push_setting_changed', { detail: { enabled: !!enabled } })
  );
}

/**
 * Checks if browser supports Web Notifications
 */
export function isNotificationSupported() {
  return typeof window !== 'undefined' && 'Notification' in window;
}

/**
 * Gets current notification permission: 'granted' | 'denied' | 'default' | 'unsupported'
 */
export function getNotificationPermission() {
  if (!isNotificationSupported()) return 'unsupported';
  return Notification.permission;
}

/**
 * Requests browser notification permission from user
 */
export async function requestNotificationPermission() {
  if (!isNotificationSupported()) return 'unsupported';
  try {
    const permission = await Notification.requestPermission();
    return permission;
  } catch (err) {
    console.warn('Failed to request notification permission:', err);
    return Notification.permission;
  }
}

/**
 * Sends Web Push & In-App notification when a video task is completed.
 * Title: [동영상 제목]
 * Body: "[동영상 제목] 자막이 생성되었습니다"
 */
export function notifyTaskCompleted(filename, onClickCallback) {
  // 1. Check if user turned notification OFF in application
  if (!isNotificationEnabled()) {
    return;
  }

  const cleanName = filename ? filename.trim() : '동영상';
  const notificationTitle = cleanName;
  const notificationBody = `${cleanName} 자막이 생성되었습니다`;

  // 2. Play subtle completion sound
  playCompletionChime();

  // 3. Always dispatch in-app floating toast popup event (guarantees visual popup appears on screen!)
  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('transm_task_completed', {
        detail: {
          filename: cleanName,
          title: notificationTitle,
          message: notificationBody,
          onClick: onClickCallback,
          timestamp: Date.now()
        }
      })
    );
  }

  // 4. Also trigger OS native desktop notification if supported
  if (isNotificationSupported()) {
    const showDesktopNotification = () => {
      try {
        const notif = new Notification(notificationTitle, {
          body: notificationBody,
          icon: '/vite.svg',
          tag: `transm-completed-${Date.now()}`,
          badge: '/vite.svg',
          requireInteraction: false
        });

        notif.onclick = () => {
          try {
            window.focus();
          } catch (_) {}
          if (typeof onClickCallback === 'function') {
            onClickCallback();
          }
          notif.close();
        };
      } catch (err) {
        console.warn('Direct Notification constructor failed, attempting serviceWorker fallback:', err);
        if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
          navigator.serviceWorker.ready.then((reg) => {
            reg.showNotification(notificationTitle, {
              body: notificationBody,
              icon: '/vite.svg',
            });
          });
        }
      }
    };

    if (Notification.permission === 'granted') {
      showDesktopNotification();
    } else if (Notification.permission === 'default') {
      Notification.requestPermission().then((permission) => {
        if (permission === 'granted') {
          showDesktopNotification();
        }
      });
    }
  }
}

