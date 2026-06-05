package main

import (
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
	"github.com/pquerna/otp/totp"
)

func TestTotpGenerateAndValidate(t *testing.T) {
	secret, _, err := totpEnroll("user@example.com")
	if err != nil {
		t.Fatal(err)
	}
	code, err := totp.GenerateCode(secret, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if !totpValidate(secret, code) {
		t.Fatalf("freshly generated code should validate")
	}
	if totpValidate(secret, "000000") {
		t.Fatalf("wrong code must not validate")
	}
}

func TestTotpLoginRequiresValidCode(t *testing.T) {
	// Generate one fixed secret for both scenarios; each scenario app seeds
	// the user with this same secret, so the TOTP code matches in both.
	fixedSecret, _, err := totpEnroll("totp@example.com")
	if err != nil {
		t.Fatal(err)
	}
	good, err := totp.GenerateCode(fixedSecret, time.Now())
	if err != nil {
		t.Fatal(err)
	}

	// Factory creates a fresh app with a user whose TOTP secret == fixedSecret.
	makeApp := func(t testing.TB) *tests.TestApp {
		app := setupApp(t.(*testing.T))
		col, _ := app.FindCollectionByNameOrId("users")
		u := core.NewRecord(col)
		u.SetEmail("totp@example.com")
		u.SetPassword("password123")
		u.Set("verified", true)
		u.Set("totpSecret", fixedSecret)
		u.Set("totpEnabled", true)
		if err := app.Save(u); err != nil {
			t.Fatalf("save user: %v", err)
		}
		return app
	}

	bad := tests.ApiScenario{
		Name:            "login wrong 2FA",
		Method:          http.MethodPost,
		URL:             "/api/loyalty/totp/login",
		Body:            strings.NewReader(`{"identity":"totp@example.com","password":"password123","code":"000000"}`),
		ExpectedStatus:  400,
		ExpectedContent: []string{"Invalid"},
		BeforeTestFunc: func(t testing.TB, app *tests.TestApp, e *core.ServeEvent) {
			registerTOTPRoutes(e)
		},
		TestAppFactory: makeApp,
	}
	bad.Test(t)

	ok := tests.ApiScenario{
		Name:            "login good 2FA",
		Method:          http.MethodPost,
		URL:             "/api/loyalty/totp/login",
		Body:            strings.NewReader(`{"identity":"totp@example.com","password":"password123","code":"` + good + `"}`),
		ExpectedStatus:  200,
		ExpectedContent: []string{`"token":`},
		BeforeTestFunc: func(t testing.TB, app *tests.TestApp, e *core.ServeEvent) {
			registerTOTPRoutes(e)
		},
		TestAppFactory: makeApp,
	}
	ok.Test(t)
}
