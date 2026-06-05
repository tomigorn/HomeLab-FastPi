package main

import (
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
)

// registerAuthGuards blocks the built-in password endpoint for users who have TOTP
// enabled, forcing them through /api/loyalty/totp/login (which validates the code).
func registerAuthGuards(app core.App) {
	app.OnRecordAuthWithPasswordRequest("users").BindFunc(func(e *core.RecordAuthWithPasswordRequestEvent) error {
		if e.Record != nil && e.Record.GetBool("totpEnabled") {
			return apis.NewBadRequestError("Two-factor authentication required — use /api/loyalty/totp/login", nil)
		}
		return e.Next()
	})
}
