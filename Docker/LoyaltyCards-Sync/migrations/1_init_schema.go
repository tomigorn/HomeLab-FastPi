package migrations

import (
	"github.com/pocketbase/pocketbase/core"
	m "github.com/pocketbase/pocketbase/migrations"
	"github.com/pocketbase/pocketbase/tools/types"
)

const OwnerRule = `@request.auth.id != "" && owner = @request.auth.id`

// InitSchema creates the cards collection + extra users fields. Callable from the
// migration and from tests; safe to call when objects already exist.
func InitSchema(app core.App) error {
	users, err := app.FindCollectionByNameOrId("users")
	if err != nil {
		return err
	}
	if users.Fields.GetByName("totpSecret") == nil {
		users.Fields.Add(&core.TextField{Name: "totpSecret", Hidden: true})
		users.Fields.Add(&core.TextField{Name: "totpPending", Hidden: true})
		users.Fields.Add(&core.BoolField{Name: "totpEnabled"})
		if err := app.Save(users); err != nil {
			return err
		}
	}

	if existing, _ := app.FindCollectionByNameOrId("cards"); existing != nil {
		return nil
	}

	cards := core.NewBaseCollection("cards")
	cards.Fields.Add(
		&core.RelationField{Name: "owner", Required: true, MaxSelect: 1, CollectionId: users.Id, CascadeDelete: true},
		&core.TextField{Name: "cardId", Required: true},
		&core.TextField{Name: "storeName", Required: true},
		&core.TextField{Name: "barcodeValue"},
		&core.TextField{Name: "barcodeFormat"},
		&core.TextField{Name: "brandColor"},
		&core.TextField{Name: "tileColor"},
		&core.TextField{Name: "logoSource"},
		&core.TextField{Name: "logoUrl"},
		&core.TextField{Name: "catalogId"},
		&core.TextField{Name: "notes"},
		&core.BoolField{Name: "favorite"},
		&core.NumberField{Name: "order"},
		&core.NumberField{Name: "lastUsedAt"},
		&core.NumberField{Name: "clientCreatedAt"},
		&core.NumberField{Name: "clientUpdatedAt"},
		&core.BoolField{Name: "deleted"},
		// Server-clock autodate fields — the sync engine pages through changes using
		// `updated` as a monotonic cursor (sort/filter), so the collection must expose it.
		&core.AutodateField{Name: "created", OnCreate: true},
		&core.AutodateField{Name: "updated", OnCreate: true, OnUpdate: true},
	)
	cards.AddIndex("idx_cards_owner_cardId", true, "owner, cardId", "")
	cards.ListRule = types.Pointer(OwnerRule)
	cards.ViewRule = types.Pointer(OwnerRule)
	cards.CreateRule = types.Pointer(OwnerRule)
	cards.UpdateRule = types.Pointer(OwnerRule)
	cards.DeleteRule = types.Pointer(OwnerRule)
	return app.Save(cards)
}

func init() {
	m.Register(func(app core.App) error {
		return InitSchema(app)
	}, func(app core.App) error {
		if c, _ := app.FindCollectionByNameOrId("cards"); c != nil {
			return app.Delete(c)
		}
		return nil
	})
}
