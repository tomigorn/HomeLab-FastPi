package main

import (
	"net/http"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pquerna/otp/totp"
)

const totpIssuer = "LoyaltyCards"

func totpEnroll(account string) (secret string, otpauthURL string, err error) {
	key, err := totp.Generate(totp.GenerateOpts{Issuer: totpIssuer, AccountName: account})
	if err != nil {
		return "", "", err
	}
	return key.Secret(), key.URL(), nil
}

func totpValidate(secret, code string) bool {
	return totp.Validate(code, secret)
}

func findUserByIdentity(app core.App, identity string) (*core.Record, error) {
	if u, err := app.FindAuthRecordByEmail("users", identity); err == nil {
		return u, nil
	}
	return app.FindFirstRecordByData("users", "username", identity)
}

func registerTOTPRoutes(se *core.ServeEvent) {
	g := se.Router.Group("/api/loyalty/totp")

	g.POST("/setup", func(e *core.RequestEvent) error {
		user := e.Auth
		if user == nil {
			return apis.NewUnauthorizedError("auth required", nil)
		}
		secret, url, err := totpEnroll(user.Email())
		if err != nil {
			return err
		}
		user.Set("totpPending", secret)
		if err := e.App.Save(user); err != nil {
			return err
		}
		return e.JSON(http.StatusOK, map[string]string{"secret": secret, "otpauthUrl": url})
	}).Bind(apis.RequireAuth())

	g.POST("/enable", func(e *core.RequestEvent) error {
		user := e.Auth
		if user == nil {
			return apis.NewUnauthorizedError("auth required", nil)
		}
		var body struct {
			Code string `json:"code"`
		}
		if err := e.BindBody(&body); err != nil {
			return err
		}
		pending := user.GetString("totpPending")
		if pending == "" || !totpValidate(pending, body.Code) {
			return apis.NewBadRequestError("invalid code", nil)
		}
		user.Set("totpSecret", pending)
		user.Set("totpPending", "")
		user.Set("totpEnabled", true)
		if err := e.App.Save(user); err != nil {
			return err
		}
		return e.JSON(http.StatusOK, map[string]bool{"enabled": true})
	}).Bind(apis.RequireAuth())

	g.POST("/disable", func(e *core.RequestEvent) error {
		user := e.Auth
		if user == nil {
			return apis.NewUnauthorizedError("auth required", nil)
		}
		var body struct {
			Code string `json:"code"`
		}
		if err := e.BindBody(&body); err != nil {
			return err
		}
		if !user.GetBool("totpEnabled") || !totpValidate(user.GetString("totpSecret"), body.Code) {
			return apis.NewBadRequestError("invalid code", nil)
		}
		user.Set("totpSecret", "")
		user.Set("totpEnabled", false)
		if err := e.App.Save(user); err != nil {
			return err
		}
		return e.JSON(http.StatusOK, map[string]bool{"enabled": false})
	}).Bind(apis.RequireAuth())

	g.POST("/required", func(e *core.RequestEvent) error {
		var body struct {
			Identity string `json:"identity"`
		}
		if err := e.BindBody(&body); err != nil {
			return err
		}
		required := false
		if u, err := findUserByIdentity(e.App, body.Identity); err == nil {
			required = u.GetBool("totpEnabled")
		}
		return e.JSON(http.StatusOK, map[string]bool{"required": required})
	})

	g.POST("/login", func(e *core.RequestEvent) error {
		var body struct {
			Identity string `json:"identity"`
			Password string `json:"password"`
			Code     string `json:"code"`
		}
		if err := e.BindBody(&body); err != nil {
			return err
		}
		u, err := findUserByIdentity(e.App, body.Identity)
		if err != nil || !u.ValidatePassword(body.Password) {
			return apis.NewBadRequestError("invalid credentials", nil)
		}
		if u.GetBool("totpEnabled") && !totpValidate(u.GetString("totpSecret"), body.Code) {
			return apis.NewBadRequestError("invalid 2FA code", nil)
		}
		return apis.RecordAuthResponse(e, u, "", nil)
	})
}
