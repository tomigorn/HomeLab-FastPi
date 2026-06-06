package migrations

import (
	"github.com/pocketbase/pocketbase/core"
	m "github.com/pocketbase/pocketbase/migrations"
)

// Additive migration (no data loss): adds image file fields to cards so the front/back card
// photos and a hand-picked logo sync across devices. The matching IndexedDB ref UUIDs sync as
// the existing text fields added in migration 2 + the client mapping.
func init() {
	m.Register(func(app core.App) error {
		cards, err := app.FindCollectionByNameOrId("cards")
		if err != nil {
			return err
		}
		const maxSize = int64(8 << 20) // 8 MiB
		mimes := []string{"image/jpeg", "image/png", "image/webp", "image/gif"}
		for _, name := range []string{"frontPhoto", "backPhoto", "logoImage"} {
			if cards.Fields.GetByName(name) == nil {
				cards.Fields.Add(&core.FileField{Name: name, MaxSelect: 1, MaxSize: maxSize, MimeTypes: mimes})
			}
		}
		return app.Save(cards)
	}, func(app core.App) error {
		return nil
	})
}
