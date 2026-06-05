package main

import (
	"log"
	"os"

	"github.com/pocketbase/pocketbase"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/plugins/migratecmd"

	_ "loyaltycards-sync/migrations"
)

func main() {
	app := pocketbase.New()
	migratecmd.MustRegister(app, app.RootCmd, migratecmd.Config{Automigrate: true})

	// C1: block standard password auth for TOTP-enabled users.
	registerAuthGuards(app)

	app.OnServe().BindFunc(func(se *core.ServeEvent) error {
		ensureSuperuser(app)
		// Set auth token duration to ~3 years (max allowed by PocketBase validation)
		// so that the PWA session effectively never expires; only explicit logout ends it.
		if uc, err := app.FindCollectionByNameOrId("users"); err == nil {
			if uc.AuthToken.Duration != 94670856 {
				uc.AuthToken.Duration = 94670856 // ~3 years (max allowed, seconds)
				_ = app.Save(uc)
			}
		}
		// I1: enable rate limiting on auth routes (6 req / 60 s per client).
		s := app.Settings()
		s.RateLimits.Enabled = true
		s.RateLimits.Rules = []core.RateLimitRule{
			{Label: "/api/loyalty/totp/", MaxRequests: 6, Duration: 60},
			{Label: "/api/collections/users/auth-with-password", MaxRequests: 6, Duration: 60},
		}
		_ = app.Save(s)
		registerTOTPRoutes(se)
		return se.Next()
	})

	if err := app.Start(); err != nil {
		log.Fatal(err)
	}
}

func ensureSuperuser(app core.App) {
	email := os.Getenv("PB_ADMIN_EMAIL")
	password := os.Getenv("PB_ADMIN_PASSWORD")
	if email == "" || password == "" {
		return
	}
	col, err := app.FindCollectionByNameOrId(core.CollectionNameSuperusers)
	if err != nil {
		return
	}
	if _, err := app.FindAuthRecordByEmail(core.CollectionNameSuperusers, email); err == nil {
		return
	}
	rec := core.NewRecord(col)
	rec.SetEmail(email)
	rec.SetPassword(password)
	if err := app.Save(rec); err != nil {
		log.Printf("ensureSuperuser: %v", err)
	}
}
