#!/usr/bin/env bash
set -euo pipefail

# Merge train: wprowadza WIELE gotowych PR-ów na main bez ręcznego klikania,
# pod branch protection strict=true ("branch must be up to date").
#
# Problem, który rozwiązuje: przy strict=true każdy merge na main flipuje
# pozostałe PR-y w BEHIND, a GitHubowy auto-merge NIGDY sam nie aktualizuje
# gałęzi — więc seria PR-ów blokuje się nawzajem i wymaga babysittingu
# (sesja #1030, 2026-08-03/04). Natywny GitHub merge queue jest niedostępny:
# repo prywatne na koncie osobistym (feature tylko dla organizacji).
#
# Jak działa: dla każdego PR-a Z KOLEJNOŚCI ARGUMENTÓW uzbraja auto-merge
# (squash), a gdy PR jest BEHIND — robi `gh pr update-branch` i czeka, aż CI
# przejdzie i auto-merge go wprowadzi. Aktualizowany jest JEDEN PR na raz:
# update wszystkich naraz marnuje minuty CI, bo każde lądowanie unieważnia
# pozostałe (koszt rośnie z ~N do ~N²/2 przebiegów CI).
#
# Dlaczego to skrypt LOKALNY, a nie workflow w Actions: update-branch wykonany
# tokenem GITHUB_TOKEN nie triggeruje workflowów (suppression GitHuba), więc
# CI na PR-ze nigdy by nie ruszyło i auto-merge nigdy by nie odpalił. Lokalny
# `gh` używa PAT-a (repo+workflow) — push z PAT-a normalnie odpala CI.
#
# Deploye z serii merge'y NIE zapchają kolejki Coolify: deploy.yml pomija
# redundantny rebuild, gdy prod serwuje już dany SHA lub jego potomka
# (koalescencja burstów, 2026-08-07).
#
# Użycie:
#   scripts/merge-train.sh 1062 1063 1064
#
# Env (opcjonalne):
#   MERGE_TRAIN_REPO                (default artur-t-96/Nexus)
#   MERGE_TRAIN_POLL_SECONDS        (default 90)
#   MERGE_TRAIN_PR_TIMEOUT_MINUTES  (default 90 — na PR; CI trwa ~22 min)

REPO="${MERGE_TRAIN_REPO:-artur-t-96/Nexus}"
POLL_SECONDS="${MERGE_TRAIN_POLL_SECONDS:-90}"
PER_PR_TIMEOUT_MINUTES="${MERGE_TRAIN_PR_TIMEOUT_MINUTES:-90}"

if [ $# -lt 1 ]; then
    echo "użycie: $0 <pr> [pr...]  (numery PR-ów w kolejności wprowadzania)" >&2
    exit 2
fi

skipped=()

for pr in "$@"; do
    echo "== PR #$pr =="
    state=$(gh pr view "$pr" --repo "$REPO" --json state --jq .state)
    if [ "$state" = "MERGED" ]; then
        echo "już zmergowany — dalej"
        continue
    fi
    if [ "$state" != "OPEN" ]; then
        echo "⚠️  pomijam (state=$state)"
        skipped+=("$pr")
        continue
    fi

    # Idempotentne: na CLEAN PR-ze z zielonym CI merguje od razu, w innym
    # stanie tylko uzbraja auto-merge na później.
    gh pr merge "$pr" --repo "$REPO" --squash --auto || true

    deadline=$(( $(date +%s) + PER_PR_TIMEOUT_MINUTES * 60 ))
    while :; do
        info=$(gh pr view "$pr" --repo "$REPO" --json state,mergeStateStatus)
        state=$(jq -r .state <<<"$info")
        mss=$(jq -r .mergeStateStatus <<<"$info")

        if [ "$state" = "MERGED" ]; then
            echo "✅ #$pr wjechał"
            break
        fi
        if [ "$state" = "CLOSED" ]; then
            echo "⚠️  #$pr zamknięty bez merge — pomijam"
            skipped+=("$pr")
            break
        fi

        case "$mss" in
            DIRTY)
                # Konflikt tekstowy z main — wymaga człowieka/agenta; nie
                # blokujemy reszty pociągu.
                echo "⚠️  #$pr ma konflikt z main — pomijam, jadę dalej"
                skipped+=("$pr")
                break
                ;;
            BEHIND)
                echo "#$pr BEHIND → gh pr update-branch (merge maina do gałęzi, CI ruszy od nowa)"
                gh pr update-branch "$pr" --repo "$REPO" \
                    || echo "update-branch nie przeszedł — ponowię w następnym obiegu"
                ;;
            *)
                # BLOCKED = CI w toku LUB nierozwiązane wątki review (przy
                # zielonych checkach patrz memory: BLOCKED mimo 5/5). UNSTABLE
                # = failuje niewymagany check. CLEAN = auto-merge zaraz zadziała.
                echo "#$pr status=$mss — czekam ${POLL_SECONDS}s (CI/auto-merge)"
                ;;
        esac

        if [ "$(date +%s)" -ge "$deadline" ]; then
            echo "⚠️  #$pr nie wjechał w ${PER_PR_TIMEOUT_MINUTES} min (status=$mss) — pomijam."
            echo "    Sprawdź: czerwony required check? nierozwiązane wątki review?"
            skipped+=("$pr")
            break
        fi
        sleep "$POLL_SECONDS"
    done
done

echo
if [ ${#skipped[@]} -gt 0 ]; then
    echo "Merge train zakończony. Pominięte PR-y (wymagają ręcznej uwagi): ${skipped[*]}"
    exit 1
fi
echo "Merge train zakończony — wszystkie PR-y wjechały."
