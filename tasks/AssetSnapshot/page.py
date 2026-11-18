from tasks.AssetSnapshot.assets import AssetSnapshotAssets
from tasks.GameUi.page import Page, page_main
from tasks.GlobalGame.assets import GlobalGameAssets


page_inventory = Page(
    AssetSnapshotAssets.I_CHECK_INVENTORY,
    key="page_inventory", name="纳物库", category="asset_snapshot",
)
page_main.connect(page_inventory, AssetSnapshotAssets.I_INVENTORY_ENTRY,
                  key="page_main->page_inventory")
page_inventory.connect(page_main, GlobalGameAssets.I_UI_BACK_YELLOW,
                       key="page_inventory->page_main")
