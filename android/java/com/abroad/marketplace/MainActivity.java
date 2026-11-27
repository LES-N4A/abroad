package com.abroad.marketplace;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Abroad on Android.
 *
 * The marketplace is a Flask application with a SQLite database, so it keeps
 * running on the computer and this app is the phone client: it opens the same
 * pages inside a WebView. The public link changes every time the Cloudflare
 * tunnel restarts, so the first screen asks for it once and remembers it.
 */
public class MainActivity extends Activity {

    private static final String PREFS = "abroad";
    private static final String KEY_URL = "server_url";
    private static final int FILE_REQ = 4001;

    private static final String OFFLINE = "https://abroad-offline.invalid/";

    private static final String INK = "#0f1b33";
    private static final String MUTED = "#65748f";
    private static final String ACCENT = "#1d4ed8";
    private static final String BG = "#f5f7fc";
    private static final String LINE = "#d5ddea";
    private static final String SURFACE = "#ffffff";

    private WebView web;
    private ValueCallback<Uri[]> pendingFiles;
    private String lastUrl;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Window window = getWindow();
        window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
        window.setStatusBarColor(Color.parseColor(INK));
        window.setNavigationBarColor(Color.parseColor(BG));

        String saved = prefs().getString(KEY_URL, "");
        if (saved == null || saved.trim().isEmpty()) {
            showSetup("");
        } else {
            openSite(saved);
        }
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private int dp(int value) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value,
                getResources().getDisplayMetrics());
    }

    private static int color(String hex) {
        return Color.parseColor(hex);
    }

    private TextView text(String content, int size, String hex, boolean bold, int gravity) {
        TextView view = new TextView(this);
        view.setText(content);
        view.setTextSize(size);
        view.setTextColor(color(hex));
        view.setGravity(gravity);
        if (bold) {
            view.setTypeface(Typeface.DEFAULT_BOLD);
        }
        view.setLineSpacing(dp(3), 1f);
        return view;
    }

    // ----------------------------------------------------------- link screen

    private void showSetup(String typed) {
        web = null;

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(color(BG));
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(dp(28), dp(48), dp(28), dp(28));

        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.logo);
        LinearLayout.LayoutParams logoParams =
                new LinearLayout.LayoutParams(dp(104), dp(104));
        logoParams.bottomMargin = dp(16);
        root.addView(logo, logoParams);

        root.addView(text("Abroad", 30, INK, true, Gravity.CENTER));

        LinearLayout.LayoutParams gap =
                new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT);
        gap.bottomMargin = dp(26);
        root.addView(text("Tunisia marketplace", 15, MUTED, false, Gravity.CENTER), gap);

        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackgroundColor(color(SURFACE));
        card.setPadding(dp(20), dp(20), dp(20), dp(22));
        LinearLayout.LayoutParams cardParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        cardParams.bottomMargin = dp(18);
        root.addView(card, cardParams);

        card.addView(text("Where is the site running?", 17, INK, true, Gravity.START));

        LinearLayout.LayoutParams helpGap = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        helpGap.topMargin = dp(8);
        helpGap.bottomMargin = dp(16);
        card.addView(text(
                "On the computer, run start-abroad.cmd then tunnel-abroad.cmd. "
                        + "Paste the public link they print here.",
                14, MUTED, false, Gravity.START), helpGap);

        final EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setTextSize(15);
        input.setTextColor(color(INK));
        input.setHintTextColor(color(MUTED));
        input.setHint("https://....trycloudflare.com");
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setText(typed);
        input.setBackgroundColor(color(BG));
        input.setPadding(dp(14), dp(14), dp(14), dp(14));
        LinearLayout.LayoutParams inputParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        inputParams.bottomMargin = dp(16);
        card.addView(input, inputParams);

        Button open = new Button(this);
        open.setText("Open marketplace");
        open.setAllCaps(false);
        open.setTextSize(16);
        open.setTextColor(Color.WHITE);
        open.setBackgroundColor(color(ACCENT));
        open.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                String url = normalise(input.getText().toString());
                if (url.isEmpty()) {
                    Toast.makeText(MainActivity.this, "Paste the link first.",
                            Toast.LENGTH_SHORT).show();
                    return;
                }
                prefs().edit().putString(KEY_URL, url).apply();
                openSite(url);
            }
        });
        card.addView(open, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(52)));

        root.addView(text(
                "The link is new every time the tunnel starts. You can change it later "
                        + "from the \"Change the link\" button that appears when the site is offline.",
                13, MUTED, false, Gravity.CENTER));

        setContentView(root);
    }

    private static String normalise(String raw) {
        String url = raw == null ? "" : raw.trim();
        if (url.isEmpty()) {
            return "";
        }
        if (!url.contains("://")) {
            url = "https://" + url;
        }
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
    }

    // ------------------------------------------------------------ the site

    private void openSite(String url) {
        lastUrl = url;
        web = new WebView(this);
        web.setBackgroundColor(color(BG));

        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String target) {
                return handleInternal(target);
            }

            @Override
            public void onReceivedError(WebView view, int code, String description,
                                        String failingUrl) {
                if (failingUrl != null && failingUrl.equals(lastUrl)) {
                    showOffline();
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (request != null && request.isForMainFrame() && request.getUrl() != null
                        && request.getUrl().toString().equals(lastUrl)) {
                    showOffline();
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (pendingFiles != null) {
                    pendingFiles.onReceiveValue(null);
                }
                pendingFiles = callback;
                Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                pick.setType("*/*");
                if (params != null && params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) {
                    pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                }
                try {
                    startActivityForResult(Intent.createChooser(pick, "Choose a file"), FILE_REQ);
                    return true;
                } catch (Exception error) {
                    pendingFiles = null;
                    return false;
                }
            }
        });

        setContentView(web);
        web.loadUrl(url);
    }

    private boolean handleInternal(String target) {
        if (target == null || !target.startsWith(OFFLINE)) {
            return false;
        }
        if (target.endsWith("retry")) {
            if (web != null && lastUrl != null) {
                web.loadUrl(lastUrl);
            }
        } else {
            showSetup(prefs().getString(KEY_URL, ""));
        }
        return true;
    }

    private void showOffline() {
        String html = "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                + "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                + "<style>body{font-family:sans-serif;background:" + BG + ";color:" + INK
                + ";margin:0;padding:48px 24px;text-align:center}"
                + "h1{font-size:22px;margin:0 0 14px}"
                + "p{color:" + MUTED + ";line-height:1.6;font-size:15px;margin:0 auto;max-width:360px}"
                + "a{display:block;margin:14px auto 0;max-width:320px;padding:15px;border-radius:16px;"
                + "text-decoration:none;font-weight:600;font-size:15px}"
                + ".p{background:" + ACCENT + ";color:#fff}"
                + ".s{background:" + SURFACE + ";color:" + ACCENT + ";border:1px solid " + LINE + "}"
                + "</style></head><body><h1>Can't reach Abroad</h1>"
                + "<p>The computer running the site is probably switched off, or the tunnel "
                + "link has changed. Start <b>start-abroad.cmd</b> and <b>tunnel-abroad.cmd</b> "
                + "on the computer, then paste the new link.</p>"
                + "<a class=\"p\" href=\"" + OFFLINE + "retry\">Try again</a>"
                + "<a class=\"s\" href=\"" + OFFLINE + "change\">Change the link</a>"
                + "</body></html>";
        if (web != null) {
            web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
        }
    }

    // --------------------------------------------------------- lifecycle bits

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_REQ) {
            if (pendingFiles != null) {
                Uri[] files = null;
                if (resultCode == RESULT_OK && data != null) {
                    files = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
                }
                pendingFiles.onReceiveValue(files);
                pendingFiles = null;
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
