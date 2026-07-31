/**
 * Shared double-confirm: first click arms (btn-primary + "Confirm"), second click runs.
 */
(function (G) {
  'use strict';

  const CONFIRM_ARM_MS = 4000;

  G.useConfirm = function useConfirm(ctx) {
    const { ref } = ctx;
    const confirmArmedKeys = ref({});
    const confirmArmedTimers = Object.create(null);

    function isConfirmArmed(key) {
      return !!(key && confirmArmedKeys.value[key]);
    }

    function clearConfirmArmed(key) {
      if (!key) return;
      if (confirmArmedTimers[key]) {
        clearTimeout(confirmArmedTimers[key]);
        delete confirmArmedTimers[key];
      }
      if (confirmArmedKeys.value[key]) {
        const next = { ...confirmArmedKeys.value };
        delete next[key];
        confirmArmedKeys.value = next;
      }
    }

    function armConfirm(key) {
      if (!key) return;
      if (confirmArmedTimers[key]) clearTimeout(confirmArmedTimers[key]);
      confirmArmedKeys.value = { ...confirmArmedKeys.value, [key]: true };
      confirmArmedTimers[key] = setTimeout(() => {
        clearConfirmArmed(key);
      }, CONFIRM_ARM_MS);
    }

    /** First click arms; second click runs action. Returns true when action ran. */
    function requestConfirm(key, action) {
      if (!isConfirmArmed(key)) {
        armConfirm(key);
        return false;
      }
      clearConfirmArmed(key);
      action();
      return true;
    }

    async function requestConfirmAsync(key, action) {
      if (!isConfirmArmed(key)) {
        armConfirm(key);
        return false;
      }
      clearConfirmArmed(key);
      await action();
      return true;
    }

    function confirmButtonClass(key, idleClass, armedClass) {
      return isConfirmArmed(key) ? (armedClass || 'btn-primary') : idleClass;
    }

    function confirmButtonLabel(key, idleLabel, busyLabel) {
      if (busyLabel) return busyLabel;
      return isConfirmArmed(key) ? 'Confirm' : idleLabel;
    }

    const api_out = {
      isConfirmArmed,
      clearConfirmArmed,
      armConfirm,
      requestConfirm,
      requestConfirmAsync,
      confirmButtonClass,
      confirmButtonLabel,
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
