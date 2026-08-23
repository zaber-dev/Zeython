from zeython import FeatureManager, FeatureServiceProvider


class AppFeatureServiceProvider(FeatureServiceProvider):
    """Registers this app's feature flags (see docs/feature-flags.md).

    ``super().boot()`` first -- it's what actually binds the
    ``FeatureManager`` this then defines flags on.
    """

    def boot(self) -> None:
        super().boot()
        manager = self.container.make(FeatureManager)
        # A deterministic 10% rollout, keyed by whatever `context` a
        # feature(request, "beta_dashboard", context) call passes -- see
        # AuthController.me for a real check. The same user always lands
        # on the same side, so it doesn't flicker across requests.
        manager.percentage("beta_dashboard", rollout=10)
        # A plain .env-controlled toggle instead, if you'd rather flip it
        # by hand than roll it out gradually:
        # manager.boolean("new_checkout")
