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

// setupAppNoMFA creates a fresh test app with our schema applied and with
// the users collection MFA disabled (we manage TOTP ourselves).
func setupAppNoMFA(t *testing.T) *tests.TestApp {
	app := setupApp(t)
	col, err := app.FindCollectionByNameOrId("users")
	if err != nil {
		t.Fatalf("users collection: %v", err)
	}
	col.MFA.Enabled = false
	if err := app.Save(col); err != nil {
		t.Fatalf("save users collection: %v", err)
	}
	return app
}

func TestStandardPasswordEndpointBlocksTotpUser(t *testing.T) {
	// 2FA-enabled user: standard auth endpoint must return 400.
	blocked := tests.ApiScenario{
		Name:            "2FA user blocked on standard password endpoint",
		Method:          http.MethodPost,
		URL:             "/api/collections/users/auth-with-password",
		Body:            strings.NewReader(`{"identity":"guard2fa@example.com","password":"password123"}`),
		ExpectedStatus:  400,
		ExpectedContent: []string{"Two-factor authentication required"},
		TestAppFactory: func(t testing.TB) *tests.TestApp {
			app := setupAppNoMFA(t.(*testing.T))
			registerAuthGuards(app)
			col, _ := app.FindCollectionByNameOrId("users")
			u := core.NewRecord(col)
			u.SetEmail("guard2fa@example.com")
			u.SetPassword("password123")
			u.Set("verified", true)
			secret, _, _ := totpEnroll("guard2fa@example.com")
			u.Set("totpSecret", secret)
			u.Set("totpEnabled", true)
			if err := app.Save(u); err != nil {
				t.Fatal(err)
			}
			return app
		},
	}
	blocked.Test(t)

	// non-2FA user: standard auth endpoint must still work (200 + token).
	okPlain := tests.ApiScenario{
		Name:            "non-2FA user allowed on standard password endpoint",
		Method:          http.MethodPost,
		URL:             "/api/collections/users/auth-with-password",
		Body:            strings.NewReader(`{"identity":"guardplain@example.com","password":"password123"}`),
		ExpectedStatus:  200,
		ExpectedContent: []string{"\"token\":"},
		TestAppFactory: func(t testing.TB) *tests.TestApp {
			app := setupAppNoMFA(t.(*testing.T))
			registerAuthGuards(app)
			col, _ := app.FindCollectionByNameOrId("users")
			u2 := core.NewRecord(col)
			u2.SetEmail("guardplain@example.com")
			u2.SetPassword("password123")
			u2.Set("verified", true)
			if err := app.Save(u2); err != nil {
				t.Fatal(err)
			}
			return app
		},
	}
	okPlain.Test(t)
}

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
