const { createApp, ref, reactive, computed, watch, nextTick, onMounted } = Vue;

const app = createApp({
  setup() {
    const ctx = Genbounty.createCtx({
      ref, reactive, computed, watch, nextTick, onMounted,
    });
    return Genbounty.useAppSetup(ctx);
  },
});
registerPayloadEditor(app);
app.mount('#app');
