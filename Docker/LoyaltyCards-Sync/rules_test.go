package main

import (
	"net/http"
	"testing"

	"loyaltycards-sync/migrations"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

// setupApp gives a fresh test app with our schema applied.
func setupApp(t *testing.T) *tests.TestApp {
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	if err := migrations.InitSchema(app); err != nil {
		t.Fatalf("init schema: %v", err)
	}
	return app
}

func makeUser(t *testing.T, app core.App, email string) *core.Record {
	col, err := app.FindCollectionByNameOrId("users")
	if err != nil {
		t.Fatalf("users collection missing: %v", err)
	}
	u := core.NewRecord(col)
	u.SetEmail(email)
	u.SetPassword("password123")
	u.Set("verified", true)
	if err := app.Save(u); err != nil {
		t.Fatalf("save user: %v", err)
	}
	return u
}

func authToken(t *testing.T, app core.App, email string) string {
	u, err := app.FindAuthRecordByEmail("users", email)
	if err != nil {
		t.Fatalf("find user %s: %v", email, err)
	}
	tok, err := u.NewAuthToken()
	if err != nil {
		t.Fatalf("token: %v", err)
	}
	return tok
}

func TestCardsCollectionExistsWithOwnerRules(t *testing.T) {
	app := setupApp(t)
	defer app.Cleanup()

	col, err := app.FindCollectionByNameOrId("cards")
	if err != nil {
		t.Fatalf("cards collection should exist: %v", err)
	}
	want := "@request.auth.id != \"\" && owner = @request.auth.id"
	if col.ListRule == nil || *col.ListRule != want {
		t.Fatalf("cards ListRule not owner-scoped: %v", col.ListRule)
	}
}

func TestUserCannotReadAnothersCard(t *testing.T) {
	app := setupApp(t)
	defer app.Cleanup()

	userA := makeUser(t, app, "a@example.com")
	makeUser(t, app, "b@example.com")

	cardsCol, _ := app.FindCollectionByNameOrId("cards")
	card := core.NewRecord(cardsCol)
	card.Set("owner", userA.Id)
	card.Set("cardId", "uuid-a-1")
	card.Set("storeName", "Migros")
	card.Set("barcodeValue", "7613269001234")
	card.Set("barcodeFormat", "ean13")
	if err := app.Save(card); err != nil {
		t.Fatalf("save card: %v", err)
	}

	scenario := tests.ApiScenario{
		Name:            "user B lists cards",
		Method:          http.MethodGet,
		URL:             "/api/collections/cards/records",
		Headers:         map[string]string{"Authorization": authToken(t, app, "b@example.com")},
		ExpectedStatus:  200,
		ExpectedContent: []string{"\"totalItems\":0"},
		TestAppFactory:  func(t testing.TB) *tests.TestApp { return app },
	}
	scenario.Test(t)
}
