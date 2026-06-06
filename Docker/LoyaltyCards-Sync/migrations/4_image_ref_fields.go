package migrations

import (
	"github.com/pocketbase/pocketbase/core"
	m "github.com/pocketbase/pocketbase/migrations"
)

// Additive migration (no data loss): adds the three IndexedDB ref-UUID text fields that
// travel alongside the matching file fields so the pull path can correctly key downloaded
// image blobs in the receiving device's IndexedDB store.
//
// Without these fields the pullImages function receives remote['frontPhotoRef'] == undefined
// and silently skips the download, meaning images never actually sync to device B.
func init() {
	m.Register(func(app core.App) error {
		cards, err := app.FindCollectionByNameOrId("cards")
		if err != nil {
			return err
		}
		changed := false
		for _, name := range []string{"frontPhotoRef", "backPhotoRef", "logoBlobRef"} {
			if cards.Fields.GetByName(name) == nil {
				cards.Fields.Add(&core.TextField{Name: name})
				changed = true
			}
		}
		if !changed {
			return nil
		}
		return app.Save(cards)
	}, func(app core.App) error {
		return nil
	})
}
