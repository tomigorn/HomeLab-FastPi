package migrations

import (
	"github.com/pocketbase/pocketbase/core"
	m "github.com/pocketbase/pocketbase/migrations"
)

// Additive migration (no data loss): adds the resolved tile background colour to cards
// (so photo/logo-derived colours sync across devices even without the blob), and the
// global sort-mode preference to the user record.
func init() {
	m.Register(func(app core.App) error {
		cards, err := app.FindCollectionByNameOrId("cards")
		if err != nil {
			return err
		}
		if cards.Fields.GetByName("bgColor") == nil {
			cards.Fields.Add(&core.TextField{Name: "bgColor"})
			if err := app.Save(cards); err != nil {
				return err
			}
		}

		users, err := app.FindCollectionByNameOrId("users")
		if err != nil {
			return err
		}
		if users.Fields.GetByName("sortMode") == nil {
			users.Fields.Add(&core.TextField{Name: "sortMode"})
			if err := app.Save(users); err != nil {
				return err
			}
		}
		return nil
	}, func(app core.App) error {
		return nil
	})
}
