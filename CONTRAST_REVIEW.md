# 译文最小对立 · 人工抽检表

由 `python contrast_sample.py --md CONTRAST_REVIEW.md` 生成。

机器已自动核验：四项互不相同、答案未被改写、2×2 每轴 2:2、除审计申报外不引入新实词、改写结果不是病句。

> 分组标题里的 `hard/medium/easy` 是「这道题逼你听日文的哪一段」：
> `head`=句首人称、`mid`=句中数量·方位·对象·具体名词、`tail`=句尾否定·时制。
> 只落在 head+tail 的题（只听开头和结尾就能选对）标为 easy，出卷时最后才用。

**人工只需判断一件事**：标 ✘ 的三项里，有没有哪一条其实也能当这句日文的合法译文？（若有，请记下题号，那说明对应那条轴的日文侧证据规则需要收紧。）

本表共 147 题，按「难度｜语法轴」分层抽样。


## 轴：easy｜modal（3 题）

**1. 日文**：私たちは、パーティーを開くための部屋を借りねばならない。　`four_way_slot`　难度 `easy`（听辨区：tail）

- ✘ We want to hire a room to hold the party in.　<sub>情态：have to → want to</sub>
- ✔ We have to hire a room to hold the party in.
- ✘ We may hire a room to hold the party in.　<sub>情态：have to → may</sub>
- ✘ We should hire a room to hold the party in.　<sub>情态：have to → should</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」

**2. 日文**：理論には実践が伴わなければならない。　`four_way_slot`　难度 `easy`（听辨区：tail）

- ✘ 理論應該與實踐相隨。　<sub>情态：必須 → 應該</sub>
- ✔ 理論必須與實踐相隨。
- ✘ 理論想與實踐相隨。　<sub>情态：必須 → 想</sub>
- ✘ 理論可以與實踐相隨。　<sub>情态：必須 → 可以</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」

**3. 日文**：そして、入国審査官の審査を受けて上陸許可を受けなければなりません。　`four_way_slot`　难度 `easy`（听辨区：tail）

- ✘ They should then go through a landing examination conducted by inspection officers before they can obtain landing permission.　<sub>情态：must → should</sub>
- ✘ They may then go through a landing examination conducted by inspection officers before they can obtain landing permission.　<sub>情态：must → may</sub>
- ✔ They must then go through a landing examination conducted by inspection officers before they can obtain landing permission.
- ✘ They want to then go through a landing examination conducted by inspection officers before they can obtain landing permission.　<sub>情态：must → want to</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」

## 轴：easy｜modal+person（3 题）

**4. 日文**：我々は太陽エネルギーを最大限に活用しなければならない。　`matrix_2x2`　难度 `easy`（听辨区：head+tail）

- ✘ They may make the best use of solar energy.　<sub>情态：must → may；人称：We → they</sub>
- ✘ They must make the best use of solar energy.　<sub>人称：We → they</sub>
- ✘ We may make the best use of solar energy.　<sub>情态：must → may</sub>
- ✔ We must make the best use of solar energy.
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里显式出现了代词（私たち），人称不是靠上下文猜的

**5. 日文**：あなたはもっと仕事をしなければなりません。　`matrix_2x2`　难度 `easy`（听辨区：head+tail）

- ✘ I may work more.　<sub>情态：must → may；人称：You → I</sub>
- ✘ I must work more.　<sub>人称：You → I</sub>
- ✘ You may work more.　<sub>情态：must → may</sub>
- ✔ You must work more.
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里显式出现了代词（あなた／君），人称不是靠上下文猜的

**6. 日文**：君は最悪の事態に備えておかなければいけない。　`matrix_2x2`　难度 `easy`（听辨区：head+tail）

- ✘ You may prepare yourself for the worst.　<sub>情态：must → may</sub>
- ✘ I may prepare yourself for the worst.　<sub>情态：must → may；人称：You → I</sub>
- ✘ I must prepare yourself for the worst.　<sub>人称：You → I</sub>
- ✔ You must prepare yourself for the worst.
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里显式出现了代词（あなた／君），人称不是靠上下文猜的

## 轴：easy｜person（3 题）

**7. 日文**：彼は紅茶を注文した。　`four_way_slot`　难度 `easy`（听辨区：head）

- ✘ 她點了一杯茶。　<sub>人称：他 → 她</sub>
- ✘ 你點了一杯茶。　<sub>人称：他 → 你</sub>
- ✔ 他點了一杯茶。
- ✘ 我點了一杯茶。　<sub>人称：他 → 我</sub>
- 依据：日文里显式出现了代词（彼）

**8. 日文**：私は仕事で忙しい。　`four_way_slot`　难度 `easy`（听辨区：head）

- ✔ I'm busy with work.
- ✘ You're busy with work.　<sub>人称：I → you</sub>
- ✘ He's busy with work.　<sub>人称：I → he</sub>
- ✘ She's busy with work.　<sub>人称：I → she</sub>
- 依据：日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**9. 日文**：私には時間もお金もない。　`four_way_slot`　难度 `easy`（听辨区：head）

- ✘ 她沒有時間，也沒有錢。　<sub>人称：我 → 她</sub>
- ✘ 他沒有時間，也沒有錢。　<sub>人称：我 → 他</sub>
- ✔ 我沒有時間，也沒有錢。
- ✘ 你沒有時間，也沒有錢。　<sub>人称：我 → 你</sub>
- 依据：日文里显式出现了代词（私／僕）

## 轴：easy｜polarity+person（3 题）

**10. 日文**：彼はどうしてもその金を受け取ろうとしなかった。　`matrix_2x2`　难度 `easy`（听辨区：head+tail）

- ✘ I would take the money.　<sub>肯否：not 被去掉；人称：He → I</sub>
- ✘ I would not take the money.　<sub>人称：He → I</sub>
- ✔ He would not take the money.
- ✘ He would take the money.　<sub>肯否：not 被去掉</sub>
- 依据：日文句尾谓语带否定形态素（ない／ません／ぬ），录音说的是「没有／不」；日文里显式出现了代词（彼），人称不是靠上下文猜的

**11. 日文**：彼はタフな奴だったよ。　`matrix_2x2`　难度 `easy`（听辨区：head+tail）

- ✘ I was not a tough guy.　<sub>肯否：was → was not；人称：He → I</sub>
- ✔ He was a tough guy.
- ✘ He was not a tough guy.　<sub>肯否：was → was not</sub>
- ✘ I was a tough guy.　<sub>人称：He → I</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里显式出现了代词（彼），人称不是靠上下文猜的

**12. 日文**：彼はペンを取り出して小切手にサインした。　`matrix_2x2`　难度 `easy`（听辨区：head+tail）

- ✔ He took out his pen to sign his check.
- ✘ He didn't take out his pen to sign his check.　<sub>肯否：took → didn't take</sub>
- ✘ I didn't take out my pen to sign my check.　<sub>肯否：took → didn't take；人称：He → I</sub>
- ✘ I took out my pen to sign my check.　<sub>人称：He → I</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里显式出现了代词（彼），人称不是靠上下文猜的

## 轴：easy｜polarity+tense（3 题）

**13. 日文**：事態は急変した。　`matrix_2x2`　难度 `easy`（听辨区：tail）

- ✘ There is no sudden change in the situation.　<sub>肯否：a → no；时制：was → is</sub>
- ✔ There was a sudden change in the situation.
- ✘ There is a sudden change in the situation.　<sub>时制：was → is</sub>
- ✘ There was no sudden change in the situation.　<sub>肯否：a → no</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

**14. 日文**：彼女はもうすぐ６０歳だ。　`matrix_2x2`　难度 `easy`（听辨区：tail）

- ✘ She is not close on sixty.　<sub>肯否：is → is not</sub>
- ✘ She was not close on sixty.　<sub>时制：is → was；肯否：was → was not</sub>
- ✔ She is close on sixty.
- ✘ She was close on sixty.　<sub>时制：is → was</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文句里没有过去助動詞「た」，说的不是已经完成的事

**15. 日文**：私のいとこは私より少し年上です。　`matrix_2x2`　难度 `easy`（听辨区：tail）

- ✘ My cousin was a little older than I.　<sub>时制：is → was</sub>
- ✔ My cousin is a little older than I.
- ✘ My cousin is not a little older than I.　<sub>肯否：is → is not</sub>
- ✘ My cousin was not a little older than I.　<sub>时制：is → was；肯否：was → was not</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文句里没有过去助動詞「た」，说的不是已经完成的事

## 轴：easy｜tense+person（3 题）

**16. 日文**：彼女は、ひとこともわからなかった。　`matrix_2x2`　难度 `easy`（听辨区：head+tail）

- ✘ She will fail to understand a single word.　<sub>时制：failed → will fail</sub>
- ✔ She failed to understand a single word.
- ✘ I failed to understand a single word.　<sub>人称：She → I</sub>
- ✘ I will fail to understand a single word.　<sub>时制：failed → will fail；人称：She → I</sub>
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里显式出现了代词（彼女），人称不是靠上下文猜的

**17. 日文**：私は夜更かしをしないことにしている。　`matrix_2x2`　难度 `easy`（听辨区：head+tail）

- ✘ You make it a rule not to sit up late.　<sub>人称：I → you</sub>
- ✘ You made it a rule not to sit up late.　<sub>时制：make → made；人称：I → you</sub>
- ✔ I make it a rule not to sit up late.
- ✘ I made it a rule not to sit up late.　<sub>时制：make → made</sub>
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**18. 日文**：彼の議論はちっとも合理的ではなかった。　`matrix_2x2`　难度 `easy`（听辨区：head+tail）

- ✘ His argument is far from rational.　<sub>时制：was → is</sub>
- ✘ My argument is far from rational.　<sub>时制：was → is；人称：His → my</sub>
- ✔ His argument was far from rational.
- ✘ My argument was far from rational.　<sub>人称：His → my</sub>
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里显式出现了代词（彼），人称不是靠上下文猜的

## 轴：hard｜comparative+polarity（3 题）

**19. 日文**：与えられるより与える方がいっそう恵まれている。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ 施比受更没有福。　<sub>肯否：有 → 没有</sub>
- ✔ 施比受更有福。
- ✘ 受比施更有福。　<sub>比较方向：施 ↔ 受 互换</sub>
- ✘ 受比施更没有福。　<sub>比较方向：施 ↔ 受 互换；肯否：有 → 没有</sub>
- 依据：日文用「〜より」显式标出了比较的基准，互换两侧后意思相反；日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事

**20. 日文**：猫は犬より小さい。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ Cats are smaller than dogs.
- ✘ Cats are not smaller than dogs.　<sub>肯否：are → are not</sub>
- ✘ Dogs are not smaller than Cats.　<sub>比较方向：Cats ↔ dogs 互换；肯否：are → are not</sub>
- ✘ Dogs are smaller than Cats.　<sub>比较方向：Cats ↔ dogs 互换</sub>
- 依据：日文用「〜より」显式标出了比较的基准，互换两侧后意思相反；日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的

**21. 日文**：女性は男性よりも低い給料で雇われている。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ Women are not employed at a lower salary than men.　<sub>肯否：are → are not</sub>
- ✔ Women are employed at a lower salary than men.
- ✘ Men are employed at a lower salary than Women.　<sub>比较方向：Women ↔ men 互换</sub>
- ✘ Men are not employed at a lower salary than Women.　<sub>比较方向：Women ↔ men 互换；肯否：are → are not</sub>
- 依据：日文用「〜より」显式标出了比较的基准，互换两侧后意思相反；日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的

## 轴：hard｜conj+modal（3 题）

**22. 日文**：恐い話が聞きたいなら、数週間前に私が見た夢のことを話してあげるよ。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ 即使你必須聽恐怖故事，那我就把幾個星期前作的夢告訴你吧。　<sub>分句逻辑：如果 → 即使；情态：想 → 必須</sub>
- ✘ 如果你必須聽恐怖故事，那我就把幾個星期前作的夢告訴你吧。　<sub>情态：想 → 必須</sub>
- ✔ 如果你想聽恐怖故事，那我就把幾個星期前作的夢告訴你吧。
- ✘ 即使你想聽恐怖故事，那我就把幾個星期前作的夢告訴你吧。　<sub>分句逻辑：如果 → 即使</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里有愿望形「〜たい」

**23. 日文**：この本を読み終わらなければならないので出かけない。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ I am not going out because I may finish reading this book.　<sub>情态：have to → may</sub>
- ✔ I am not going out because I have to finish reading this book.
- ✘ I am not going out although I may finish reading this book.　<sub>分句逻辑：because → although；情态：have to → may</sub>
- ✘ I am not going out although I have to finish reading this book.　<sub>分句逻辑：because → although</sub>
- 依据：日文里有表示原因的「から／ので」，没有逆接的「のに／けど」；日文里有义务表达「〜なければならない／〜ないといけない」

**24. 日文**：私たちは勉強したいので学校へ行きます。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ We go to school although we want to learn.　<sub>分句逻辑：because → although</sub>
- ✔ We go to school because we want to learn.
- ✘ We go to school because we have to learn.　<sub>情态：want to → have to</sub>
- ✘ We go to school although we have to learn.　<sub>分句逻辑：because → although；情态：want to → have to</sub>
- 依据：日文里有表示原因的「から／ので」，没有逆接的「のに／けど」；日文里有愿望形「〜たい」

## 轴：hard｜conj+person（3 题）

**25. 日文**：「終電逃したらどうしよう」「帰れなかったらうち泊めてやるよ」　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ "What should I do even if I miss the last train?" "If you aren't able to get back home then you can stay here."　<sub>分句逻辑：if → even if</sub>
- ✘ "What should he does if he misses the last train?" "If you aren't able to get back home then you can stay here."　<sub>人称：I → he</sub>
- ✘ "What should he does even if he misses the last train?" "If you aren't able to get back home then you can stay here."　<sub>分句逻辑：if → even if；人称：I → he</sub>
- ✔ "What should I do if I miss the last train?" "If you aren't able to get back home then you can stay here."
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**26. 日文**：妻が電話してきたら、私は重要な会議中で出られないと言ってください。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ If your wife calls, just tell her you're in an important meeting and cannot be disturbed.　<sub>人称：my → your</sub>
- ✘ Even if my wife calls, just tell her I'm in an important meeting and cannot be disturbed.　<sub>分句逻辑：If → even if</sub>
- ✔ If my wife calls, just tell her I'm in an important meeting and cannot be disturbed.
- ✘ Even if your wife calls, just tell her you're in an important meeting and cannot be disturbed.　<sub>分句逻辑：If → even if；人称：my → your</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**27. 日文**：彼が熱を出して寝ていると知っていたら、私は彼の面倒を見ていただろう。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ You would have taken care of him if you had known that he was ill with a fever.　<sub>人称：I → you</sub>
- ✔ I would have taken care of him if I had known that he was ill with a fever.
- ✘ I would have taken care of him even if I had known that he was ill with a fever.　<sub>分句逻辑：if → even if</sub>
- ✘ You would have taken care of him even if you had known that he was ill with a fever.　<sub>分句逻辑：if → even if；人称：I → you</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

## 轴：hard｜lexical+modal（3 题）

**28. 日文**：この夏は、何の映画が観たい？　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ What movies do you have to see this summer?　<sub>情态：want to → have to</sub>
- ✔ What movies do you want to see this summer?
- ✘ What movies do you want to see this winter?　<sub>具体名词：summer → winter</sub>
- ✘ What movies do you have to see this winter?　<sub>具体名词：summer → winter；情态：want to → have to</sub>
- 依据：日文里明确说的是「夏」，换成同类的别的东西就与录音不符；日文里有愿望形「〜たい」

**29. 日文**：母の世話をしないといけないの。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ I have to take care of my mother.
- ✘ I have to take care of my father.　<sub>具体名词：mother → father</sub>
- ✘ I may take care of my mother.　<sub>情态：have to → may</sub>
- ✘ I may take care of my father.　<sub>具体名词：mother → father；情态：have to → may</sub>
- 依据：日文里明确说的是「母」，换成同类的别的东西就与录音不符；日文里有义务表达「〜なければならない／〜ないといけない」

**30. 日文**：その子から目を離さないようにしなければいけない。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ You must keep an eye on the child.
- ✘ You may keep a hand on the child.　<sub>具体名词：eye → hand；情态：must → may</sub>
- ✘ You may keep an eye on the child.　<sub>情态：must → may</sub>
- ✘ You must keep a hand on the child.　<sub>具体名词：eye → hand</sub>
- 依据：日文里明确说的是「目」，换成同类的别的东西就与录音不符；日文里有义务表达「〜なければならない／〜ないといけない」

## 轴：hard｜lexical+person（3 题）

**31. 日文**：父は私が時間を守らないと言って叱った。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✔ My father scolded me for not being punctual.
- ✘ Your father scolded you for not being punctual.　<sub>人称：My → your</sub>
- ✘ Your mother scolded you for not being punctual.　<sub>具体名词：father → mother；人称：My → your</sub>
- ✘ My mother scolded me for not being punctual.　<sub>具体名词：father → mother</sub>
- 依据：日文里明确说的是「父」，换成同类的别的东西就与录音不符；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**32. 日文**：彼は、英語だけでなくタイ語も話せます。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ He can speak Thai as well as Japanese.　<sub>具体名词：English → Japanese</sub>
- ✘ I can speak Thai as well as English.　<sub>人称：He → I</sub>
- ✔ He can speak Thai as well as English.
- ✘ I can speak Thai as well as Japanese.　<sub>具体名词：English → Japanese；人称：He → I</sub>
- 依据：日文里明确说的是「英語」，换成同类的别的东西就与录音不符；日文里显式出现了代词（彼），人称不是靠上下文猜的

**33. 日文**：彼は転んだときに手を傷つけた。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ 他摔倒的时候弄伤了脚。　<sub>具体名词：手 → 脚</sub>
- ✔ 他摔倒的时候弄伤了手。
- ✘ 我摔倒的时候弄伤了脚。　<sub>具体名词：手 → 脚；人称：他 → 我</sub>
- ✘ 我摔倒的时候弄伤了手。　<sub>人称：他 → 我</sub>
- 依据：日文里明确说的是「手」，换成同类的别的东西就与录音不符；日文里显式出现了代词（彼）

## 轴：hard｜lexical+tense（3 题）

**34. 日文**：僕はしょっちゅう電車の中に傘を忘れてしまう。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ I am always leaving my umbrella on the train.
- ✘ I was always leaving my umbrella on the train.　<sub>时制：am → was</sub>
- ✘ I am always leaving my umbrella on the bus.　<sub>具体名词：train → bus</sub>
- ✘ I was always leaving my umbrella on the bus.　<sub>具体名词：train → bus；时制：am → was</sub>
- 依据：日文里明确说的是「電車」，换成同类的别的东西就与录音不符；日文句里没有过去助動詞「た」，说的不是已经完成的事

**35. 日文**：いいや。あいつは水がキライなんだ。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ No. He didn't like water!　<sub>时制：doesn't → didn't</sub>
- ✔ No. He doesn't like water!
- ✘ No. He didn't like coffee!　<sub>具体名词：water → coffee；时制：doesn't → didn't</sub>
- ✘ No. He doesn't like coffee!　<sub>具体名词：water → coffee</sub>
- 依据：日文里明确说的是「水」，换成同类的别的东西就与录音不符；日文句里没有过去助動詞「た」，说的不是已经完成的事

**36. 日文**：健とジョーはテニスをしに公園へ行ったわよ。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ Ken and Joe went to the station to play tennis.　<sub>具体名词：park → station</sub>
- ✘ Ken and Joe will go to the station to play tennis.　<sub>具体名词：park → station；时制：went → will go</sub>
- ✔ Ken and Joe went to the park to play tennis.
- ✘ Ken and Joe will go to the park to play tennis.　<sub>时制：went → will go</sub>
- 依据：日文里明确说的是「公園」，换成同类的别的东西就与录音不符；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

## 轴：hard｜modal+person（3 题）

**37. 日文**：ジョンはこのところ酒を飲みすぎている。彼がこれ以上酒を飲むのをやめさせなければならない。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ John drinks too much these days. We may stop me from drinking any more.　<sub>情态：have to → may；人称：him → me</sub>
- ✘ John drinks too much these days. We may stop him from drinking any more.　<sub>情态：have to → may</sub>
- ✔ John drinks too much these days. We have to stop him from drinking any more.
- ✘ John drinks too much these days. We have to stop me from drinking any more.　<sub>人称：him → me</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里显式出现了代词（彼），人称不是靠上下文猜的

**38. 日文**：あなたに会いたいという人がいます。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ 有一个人想见你。
- ✘ 有一个人想见我。　<sub>人称：你 → 我</sub>
- ✘ 有一个人必须见我。　<sub>情态：想 → 必须；人称：你 → 我</sub>
- ✘ 有一个人必须见你。　<sub>情态：想 → 必须</sub>
- 依据：日文里有愿望形「〜たい」；日文里显式出现了代词（あなた／君）

**39. 日文**：朝のうちに彼に電話をしなければいけない。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ I may call you sometimes during the morning.　<sub>情态：must → may；人称：him → you</sub>
- ✘ I must call you sometimes during the morning.　<sub>人称：him → you</sub>
- ✔ I must call him sometimes during the morning.
- ✘ I may call him sometimes during the morning.　<sub>情态：must → may</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里显式出现了代词（彼），人称不是靠上下文猜的

## 轴：hard｜person+number（3 题）

**40. 日文**：私は１９７２年１０月１０日に生まれました。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ 你在一九七二年十月十日出生。　<sub>人称：我 → 你</sub>
- ✘ 你在一九七二年八月十日出生。　<sub>人称：我 → 你；数量：十 → 八</sub>
- ✘ 我在一九七二年八月十日出生。　<sub>数量：十 → 八</sub>
- ✔ 我在一九七二年十月十日出生。
- 依据：日文里显式出现了代词（私／僕）；日文里出现数词「10」，数量是显式的

**41. 日文**：彼は昨日は一晩中勉強しました。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✔ 他昨天念了一整晚的書。
- ✘ 我昨天念了两整晚的書。　<sub>人称：他 → 我；数量：一 → 两</sub>
- ✘ 我昨天念了一整晚的書。　<sub>人称：他 → 我</sub>
- ✘ 他昨天念了两整晚的書。　<sub>数量：一 → 两</sub>
- 依据：日文里显式出现了代词（彼）；日文里出现数词「1」，数量是显式的

**42. 日文**：私は彼女と一時間話した。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ 你跟她谈了两小时。　<sub>人称：我 → 你；数量：一 → 两</sub>
- ✘ 我跟她谈了两小时。　<sub>数量：一 → 两</sub>
- ✔ 我跟她谈了一小时。
- ✘ 你跟她谈了一小时。　<sub>人称：我 → 你</sub>
- 依据：日文里显式出现了代词（私／僕）；日文里出现数词「1」，数量是显式的

## 轴：hard｜person+time（3 题）

**43. 日文**：彼は今日は休みです。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ 我今天放假。　<sub>人称：他 → 我</sub>
- ✘ 我昨天放假。　<sub>人称：他 → 我；时间：今天 → 昨天</sub>
- ✔ 他今天放假。
- ✘ 他昨天放假。　<sub>时间：今天 → 昨天</sub>
- 依据：日文里显式出现了代词（彼）；日文里出现時間名詞「今日」，时间点是显式的

**44. 日文**：列車に乗り遅れないように彼は朝早く家を出た。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ He left home early in the noon so as not to miss his train.　<sub>时间：morning → noon</sub>
- ✘ I left home early in the morning so as not to miss my train.　<sub>人称：He → I</sub>
- ✘ I left home early in the noon so as not to miss my train.　<sub>人称：He → I；时间：morning → noon</sub>
- ✔ He left home early in the morning so as not to miss his train.
- 依据：日文里显式出现了代词（彼），人称不是靠上下文猜的；日文里出现時間名詞「朝」，时间点是显式的

**45. 日文**：彼女は昨日、何もすることがなかった。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ 我昨天没事干。　<sub>人称：她 → 我</sub>
- ✔ 她昨天没事干。
- ✘ 我今天没事干。　<sub>人称：她 → 我；时间：昨天 → 今天</sub>
- ✘ 她今天没事干。　<sub>时间：昨天 → 今天</sub>
- 依据：日文里显式出现了代词（彼女）；日文里出现時間名詞「昨日」，时间点是显式的

## 轴：hard｜polarity+conj（3 题）

**46. 日文**：私は文を書く前に頭の中で整えることにしている。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ I don't make a point of arranging sentences in my mind before writing them down.　<sub>肯否：make → don't make</sub>
- ✘ I don't make a point of arranging sentences in my mind after writing them down.　<sub>肯否：make → don't make；分句逻辑：before → after</sub>
- ✔ I make a point of arranging sentences in my mind before writing them down.
- ✘ I make a point of arranging sentences in my mind after writing them down.　<sub>分句逻辑：before → after</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里有「〜前に」，先后顺序是显式的

**47. 日文**：日没前に仕事を終えるよう全力をつくしてやった。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ We went all out to finish the work before dark.
- ✘ We went all out to finish the work after dark.　<sub>分句逻辑：before → after</sub>
- ✘ We didn't go all out to finish the work after dark.　<sub>肯否：went → didn't go；分句逻辑：before → after</sub>
- ✘ We didn't go all out to finish the work before dark.　<sub>肯否：went → didn't go</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里有「〜前に」，先后顺序是显式的

**48. 日文**：出来れば、釣りに行きたい。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ I'd like to go fishing if possible.
- ✘ I wouldn't like to go fishing if possible.　<sub>肯否：'d →  wouldn't</sub>
- ✘ I'd like to go fishing even if possible.　<sub>分句逻辑：if → even if</sub>
- ✘ I wouldn't like to go fishing even if possible.　<sub>肯否：'d →  wouldn't；分句逻辑：if → even if</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里有条件形「〜たら／〜ば／〜なら」

## 轴：hard｜polarity+direction（3 题）

**49. 日文**：彼女はボストンからシカゴ経由でサンフランシスコへ旅行した。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ She didn't travel from Boston to San Francisco via Chicago.　<sub>肯否：traveled → didn't travel</sub>
- ✘ She traveled from San Francisco to Boston via Chicago.　<sub>起讫点：from Boston to San Francisco → from San Francisco to Boston</sub>
- ✘ She didn't travel from San Francisco to Boston via Chicago.　<sub>肯否：traveled → didn't travel；起讫点：from Boston to San Francisco → from San Francisco to Boston</sub>
- ✔ She traveled from Boston to San Francisco via Chicago.
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文用「〜から」「〜へ／まで」显式标出了起点和终点

**50. 日文**：彼女は一から十まで数えることができる。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ She cannot count from one to ten.　<sub>肯否：can → cannot</sub>
- ✘ She can count from ten to one.　<sub>起讫点：from one to ten → from ten to one</sub>
- ✘ She cannot count from ten to one.　<sub>肯否：can → cannot；起讫点：from one to ten → from ten to one</sub>
- ✔ She can count from one to ten.
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文用「〜から」「〜へ／まで」显式标出了起点和终点

**51. 日文**：その道は東京から大阪まで続いている。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ The road runs from Tokyo to Osaka.
- ✘ The road runs from Osaka to Tokyo.　<sub>起讫点：from Tokyo to Osaka → from Osaka to Tokyo</sub>
- ✘ The road doesn't run from Tokyo to Osaka.　<sub>肯否：runs → doesn't run</sub>
- ✘ The road doesn't run from Osaka to Tokyo.　<sub>肯否：runs → doesn't run；起讫点：from Tokyo to Osaka → from Osaka to Tokyo</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文用「〜から」「〜へ／まで」显式标出了起点和终点

## 轴：hard｜polarity+lexical（3 题）

**52. 日文**：この本は子供を対象とした本です。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ It's not a book for children.　<sub>肯否：'s → 's not</sub>
- ✘ It's a newspaper for children.　<sub>具体名词：book → newspaper</sub>
- ✘ It's not a newspaper for children.　<sub>肯否：'s → 's not；具体名词：book → newspaper</sub>
- ✔ It's a book for children.
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里明确说的是「本」，换成同类的别的东西就与录音不符

**53. 日文**：やっと、僕の姉ちゃん婚約したんだ。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ Finally, my sister got engaged.
- ✘ Finally, my sister didn't get engaged.　<sub>肯否：got → didn't get</sub>
- ✘ Finally, my father didn't get engaged.　<sub>肯否：got → didn't get；具体名词：sister → father</sub>
- ✘ Finally, my father got engaged.　<sub>具体名词：sister → father</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里明确说的是「姉」，换成同类的别的东西就与录音不符

**54. 日文**：私はお茶が好きです。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ 我不喜欢茶。　<sub>肯否：喜欢 → 不喜欢</sub>
- ✘ 我喜欢咖啡。　<sub>具体名词：茶 → 咖啡</sub>
- ✘ 我不喜欢咖啡。　<sub>肯否：喜欢 → 不喜欢；具体名词：茶 → 咖啡</sub>
- ✔ 我喜欢茶。
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事；日文里明确说的是「お茶」，换成同类的别的东西就与录音不符

## 轴：hard｜polarity+number（3 题）

**55. 日文**：私は6時に起きた。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ I didn't get up at six.　<sub>肯否：got → didn't get</sub>
- ✔ I got up at six.
- ✘ I didn't get up at seven.　<sub>肯否：got → didn't get；数量：six → seven</sub>
- ✘ I got up at seven.　<sub>数量：six → seven</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现数词「6」，数量是显式的

**56. 日文**：彼女は、１日中働いている。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ 她已經工作了两整天。　<sub>数量：一 → 两</sub>
- ✘ 她已經没工作两整天。　<sub>肯否：工作了 → 没工作；数量：一 → 两</sub>
- ✘ 她已經没工作一整天。　<sub>肯否：工作了 → 没工作</sub>
- ✔ 她已經工作了一整天。
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事；日文里出现数词「1」，数量是显式的

**57. 日文**：私は毎晩１１時に寝る。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ I go to bed at eleven every night.
- ✘ I don't go to bed at eleven every night.　<sub>肯否：go → don't go</sub>
- ✘ I go to bed at twelve every night.　<sub>数量：eleven → twelve</sub>
- ✘ I don't go to bed at twelve every night.　<sub>肯否：go → don't go；数量：eleven → twelve</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现数词「11」，数量是显式的

## 轴：hard｜polarity+person（3 题）

**58. 日文**：私は彼女の小説を愛読している。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ I don't like your novel.　<sub>肯否：like → don't like；人称：her → your</sub>
- ✘ I don't like her novel.　<sub>肯否：like → don't like</sub>
- ✔ I like her novel.
- ✘ I like your novel.　<sub>人称：her → your</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里显式出现了代词（彼女），人称不是靠上下文猜的

**59. 日文**：私よりお兄ちゃんのことが好きなの？　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ Don't you love his brother more than him?　<sub>肯否：Do → Don't；人称：my → his</sub>
- ✘ Do you love his brother more than him?　<sub>人称：my → his</sub>
- ✔ Do you love my brother more than me?
- ✘ Don't you love my brother more than me?　<sub>肯否：Do → Don't</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），问的是肯定的事；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**60. 日文**：彼の言うことは当てにならないよ。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ You must rely on my word.　<sub>肯否：not 被去掉；人称：his → my</sub>
- ✘ You must not rely on my word.　<sub>人称：his → my</sub>
- ✘ You must rely on his word.　<sub>肯否：not 被去掉</sub>
- ✔ You must not rely on his word.
- 依据：日文句尾谓语带否定形态素（ない／ません／ぬ），录音说的是「没有／不」；日文里显式出现了代词（彼），人称不是靠上下文猜的

## 轴：hard｜polarity+place（3 题）

**61. 日文**：友達の消しゴムが机の下に転がっていった。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ My friend’s eraser went rolling under the desk.
- ✘ My friend’s eraser didn't go rolling under the desk.　<sub>肯否：went → didn't go</sub>
- ✘ My friend’s eraser didn't go rolling on the desk.　<sub>肯否：went → didn't go；方位：under → on</sub>
- ✘ My friend’s eraser went rolling on the desk.　<sub>方位：under → on</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现方位名词「下」，位置关系是显式的

**62. 日文**：私の家の後ろには教会がある。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ There's a church behind my house.
- ✘ There's a church in front of my house.　<sub>方位：behind → in front of</sub>
- ✘ There's no church behind my house.　<sub>肯否：a → no</sub>
- ✘ There's no church in front of my house.　<sub>肯否：a → no；方位：behind → in front of</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现方位名词「後ろ」，位置关系是显式的

**63. 日文**：私は店の前でトムに会いました。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ I didn't meet Tom behind the store.　<sub>肯否：met → didn't meet；方位：in front of → behind</sub>
- ✘ I didn't meet Tom in front of the store.　<sub>肯否：met → didn't meet</sub>
- ✔ I met Tom in front of the store.
- ✘ I met Tom behind the store.　<sub>方位：in front of → behind</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现方位名词「前」，位置关系是显式的

## 轴：hard｜polarity+time（3 题）

**64. 日文**：明日は雨が降るでしょうか。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ 今天会下雨吗？　<sub>时间：明天 → 今天</sub>
- ✘ 今天不会下雨吗？　<sub>肯否：会 → 不会；时间：明天 → 今天</sub>
- ✔ 明天会下雨吗？
- ✘ 明天不会下雨吗？　<sub>肯否：会 → 不会</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事；日文里出现時間名詞「明日」，时间点是显式的

**65. 日文**：先週の土曜日、公園へ行った。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ 上個星期六我沒去公園。　<sub>肯否：去了 → 沒去</sub>
- ✘ 上個星期一我去了公園。　<sub>时间：星期六 → 星期一</sub>
- ✘ 上個星期一我沒去公園。　<sub>肯否：去了 → 沒去；时间：星期六 → 星期一</sub>
- ✔ 上個星期六我去了公園。
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事；日文里出现時間名詞「土曜日」，时间点是显式的

**66. 日文**：今日はピクニックに行くには寒すぎるよ。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ It is not too cold for a picnic today.　<sub>肯否：is → is not</sub>
- ✘ It is not too cold for a picnic yesterday.　<sub>肯否：is → is not；时间：today → yesterday</sub>
- ✔ It is too cold for a picnic today.
- ✘ It is too cold for a picnic yesterday.　<sub>时间：today → yesterday</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现時間名詞「今日」，时间点是显式的

## 轴：hard｜quant+person（3 题）

**67. 日文**：彼はもう帰宅しました。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✔ He has already gone home.
- ✘ I have already gone home.　<sub>人称：He → I</sub>
- ✘ He has not yet gone home.　<sub>频度量化：already → not yet</sub>
- ✘ I have not yet gone home.　<sub>频度量化：already → not yet；人称：He → I</sub>
- 依据：日文里有「もう／すでに」；日文里显式出现了代词（彼），人称不是靠上下文猜的

**68. 日文**：私の髪はまだ洗ったばかりで濡れていた。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✘ My hair was no longer wet from being washed.　<sub>频度量化：still → no longer</sub>
- ✔ My hair was still wet from being washed.
- ✘ Your hair was still wet from being washed.　<sub>人称：My → your</sub>
- ✘ Your hair was no longer wet from being washed.　<sub>频度量化：still → no longer；人称：My → your</sub>
- 依据：日文里有「まだ」；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**69. 日文**：私の部屋には、たくさんの本があるんです。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✔ 我房間裡有很多書。
- ✘ 我房間裡有很少書。　<sub>频度量化：很多 → 很少</sub>
- ✘ 你房間裡有很少書。　<sub>频度量化：很多 → 很少；人称：我 → 你</sub>
- ✘ 你房間裡有很多書。　<sub>人称：我 → 你</sub>
- 依据：日文里有「たくさん／多く」；日文里显式出现了代词（私／僕）

## 轴：hard｜quant+tense（3 题）

**70. 日文**：全てを捨ててこのレストランをやる目的はひとつだけでした。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ I had also one aim in throwing everything away to run this restaurant.　<sub>频度量化：only → also</sub>
- ✘ I will have only one aim in throwing everything away to run this restaurant.　<sub>时制：had → will have</sub>
- ✔ I had only one aim in throwing everything away to run this restaurant.
- ✘ I will have also one aim in throwing everything away to run this restaurant.　<sub>频度量化：only → also；时制：had → will have</sub>
- 依据：日文里有「だけ／しか」；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

**71. 日文**：私たちは時々彼らに会う。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ 我們有時看見了他們。　<sub>时制：會看見 → 看見了</sub>
- ✘ 我們總是看見了他們。　<sub>频度量化：有時 → 總是；时制：會看見 → 看見了</sub>
- ✘ 我們總是會看見他們。　<sub>频度量化：有時 → 總是</sub>
- ✔ 我們有時會看見他們。
- 依据：日文里有「時々／たまに」；日文句里没有过去助動詞「た」，说的不是已经完成的事

**72. 日文**：私にはするべき仕事がたくさんある。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ 我有很少工作做了。　<sub>频度量化：很多 → 很少；时制：要做 → 做了</sub>
- ✘ 我有很多工作做了。　<sub>时制：要做 → 做了</sub>
- ✔ 我有很多工作要做。
- ✘ 我有很少工作要做。　<sub>频度量化：很多 → 很少</sub>
- 依据：日文里有「たくさん／多く」；日文句里没有过去助動詞「た」，说的不是已经完成的事

## 轴：hard｜role+polarity（3 题）

**73. 日文**：彼は私を見ると逃げた。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ He ran away at the sight of me.
- ✘ I didn't run away at the sight of him.　<sub>施受：He ↔ me 施受互换；肯否：ran → didn't run</sub>
- ✘ He didn't run away at the sight of me.　<sub>肯否：ran → didn't run</sub>
- ✘ I ran away at the sight of him.　<sub>施受：He ↔ me 施受互换</sub>
- 依据：日文里表示对象的代词带「を/に」格助词，施受方向是显式的；日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的

**74. 日文**：彼女は私をバレエに招待してくれた。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ I didn't invite her to the ballet.　<sub>施受：She ↔ me 施受互换；肯否：invited → didn't invite</sub>
- ✘ I invited her to the ballet.　<sub>施受：She ↔ me 施受互换</sub>
- ✘ She didn't invite me to the ballet.　<sub>肯否：invited → didn't invite</sub>
- ✔ She invited me to the ballet.
- 依据：日文里表示对象的代词带「を/に」格助词，施受方向是显式的；日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的

**75. 日文**：彼は私にプレゼントを送ってくれた。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ He didn't send me a present.　<sub>肯否：sent → didn't send</sub>
- ✘ I sent him a present.　<sub>施受：He ↔ me 施受互换</sub>
- ✔ He sent me a present.
- ✘ I didn't send him a present.　<sub>施受：He ↔ me 施受互换；肯否：sent → didn't send</sub>
- 依据：日文里表示对象的代词带「を/に」格助词，施受方向是显式的；日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的

## 轴：hard｜tense+number（3 题）

**76. 日文**：冷蔵庫の中にバターが２ポンドある。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ There were three pounds of butter in the icebox.　<sub>时制：are → were；数量：two → three</sub>
- ✘ There were two pounds of butter in the icebox.　<sub>时制：are → were</sub>
- ✔ There are two pounds of butter in the icebox.
- ✘ There are three pounds of butter in the icebox.　<sub>数量：two → three</sub>
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里出现数词「2」，数量是显式的

**77. 日文**：カメラを３０ドルで買ったよ。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ 我花30美元會買一台照相機。　<sub>时制：買了 → 會買</sub>
- ✘ 我花40美元買了一台照相機。　<sub>数量：30 → 40</sub>
- ✔ 我花30美元買了一台照相機。
- ✘ 我花40美元會買一台照相機。　<sub>时制：買了 → 會買；数量：30 → 40</sub>
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里出现数词「30」，数量是显式的

**78. 日文**：１０人もの学生が全く同時に立ち上がった。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ As many as eleven students will stand up all at once.　<sub>时制：stood → will stand；数量：ten → eleven</sub>
- ✘ As many as eleven students stood up all at once.　<sub>数量：ten → eleven</sub>
- ✔ As many as ten students stood up all at once.
- ✘ As many as ten students will stand up all at once.　<sub>时制：stood → will stand</sub>
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里出现数词「10」，数量是显式的

## 轴：hard｜tense+person（3 题）

**79. 日文**：彼が選挙に勝つ望みはほとんどない。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ There was little hope of my winning the election.　<sub>时制：is → was；人称：his → my</sub>
- ✔ There is little hope of his winning the election.
- ✘ There was little hope of his winning the election.　<sub>时制：is → was</sub>
- ✘ There is little hope of my winning the election.　<sub>人称：his → my</sub>
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里显式出现了代词（彼），人称不是靠上下文猜的

**80. 日文**：もったいない精神は僕の性に合いませんでした。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ Thriftiness is against my nature.　<sub>时制：was → is</sub>
- ✘ Thriftiness is against your nature.　<sub>时制：was → is；人称：my → your</sub>
- ✘ Thriftiness was against your nature.　<sub>人称：my → your</sub>
- ✔ Thriftiness was against my nature.
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**81. 日文**：やってみたが、彼と連絡をとることができなかった。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ I will find it impossible to get in contact with him.　<sub>时制：found → will find</sub>
- ✘ I found it impossible to get in contact with you.　<sub>人称：him → you</sub>
- ✘ I will find it impossible to get in contact with you.　<sub>时制：found → will find；人称：him → you</sub>
- ✔ I found it impossible to get in contact with him.
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里显式出现了代词（彼），人称不是靠上下文猜的

## 轴：hard｜tense+quant（3 题）

**82. 日文**：解決しなければならない問題がたくさんある。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ There are few problems to solve.　<sub>频度量化：many → few</sub>
- ✘ There were many problems to solve.　<sub>时制：are → were</sub>
- ✘ There were few problems to solve.　<sub>时制：are → were；频度量化：many → few</sub>
- ✔ There are many problems to solve.
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里有「たくさん／多く」

**83. 日文**：最終的に2人だけが残った。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ In the end also 2 people remained.　<sub>频度量化：only → also</sub>
- ✘ In the end also 2 people will remain.　<sub>时制：remained → will remain；频度量化：only → also</sub>
- ✘ In the end only 2 people will remain.　<sub>时制：remained → will remain</sub>
- ✔ In the end only 2 people remained.
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里有「だけ／しか」

**84. 日文**：当社は、品質の良いものしか販売しておりません。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ Our company also sells quality goods.　<sub>频度量化：only → also</sub>
- ✘ Our company only sold quality goods.　<sub>时制：sells → sold</sub>
- ✔ Our company only sells quality goods.
- ✘ Our company also sold quality goods.　<sub>时制：sells → sold；频度量化：only → also</sub>
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里有「だけ／しか」

## 轴：medium｜conj+lexical（3 题）

**85. 日文**：もし残っていたらコーヒーを少しください。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ Give me some coffee even if there is any left.　<sub>分句逻辑：if → even if</sub>
- ✘ Give me some tea if there is any left.　<sub>具体名词：coffee → tea</sub>
- ✔ Give me some coffee if there is any left.
- ✘ Give me some tea even if there is any left.　<sub>分句逻辑：if → even if；具体名词：coffee → tea</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里明确说的是「コーヒー」，换成同类的别的东西就与录音不符

**86. 日文**：質問があれば手を挙げなさい。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ Raise your foot even if you have a question.　<sub>分句逻辑：if → even if；具体名词：hand → foot</sub>
- ✘ Raise your hand even if you have a question.　<sub>分句逻辑：if → even if</sub>
- ✔ Raise your hand if you have a question.
- ✘ Raise your foot if you have a question.　<sub>具体名词：hand → foot</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里明确说的是「手」，换成同类的别的东西就与录音不符

**87. 日文**：僕ならその馬に賭けたりはしない。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✔ I wouldn't bet on that horse if I were you.
- ✘ I wouldn't bet on that horse even if I were you.　<sub>分句逻辑：if → even if</sub>
- ✘ I wouldn't bet on that dog if I were you.　<sub>具体名词：horse → dog</sub>
- ✘ I wouldn't bet on that dog even if I were you.　<sub>分句逻辑：if → even if；具体名词：horse → dog</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里明确说的是「馬」，换成同类的别的东西就与录音不符

## 轴：medium｜conj+person（3 题）

**88. 日文**：七夕は漫画によく出てくるので、私もそこそこ知っています。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 七夕在漫畫裡常常出現所以你也了解它的意思。　<sub>人称：我 → 你</sub>
- ✘ 七夕在漫畫裡常常出現但是你也了解它的意思。　<sub>分句逻辑：所以 → 但是；人称：我 → 你</sub>
- ✘ 七夕在漫畫裡常常出現但是我也了解它的意思。　<sub>分句逻辑：所以 → 但是</sub>
- ✔ 七夕在漫畫裡常常出現所以我也了解它的意思。
- 依据：日文里有表示原因的「から／ので」，没有逆接的「のに／けど」；日文里显式出现了代词（私／僕）

**89. 日文**：あなたが助けてくれなかったら私はおぼれていたことでしょう。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ If it had not been for your help, he should have drowned.　<sub>人称：I → he</sub>
- ✘ Even if it had not been for your help, he should have drowned.　<sub>分句逻辑：If → even if；人称：I → he</sub>
- ✘ Even if it had not been for your help, I should have drowned.　<sub>分句逻辑：If → even if</sub>
- ✔ If it had not been for your help, I should have drowned.
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**90. 日文**：君のパスポート見つけたら、電話するね。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ If I find his passport, I'll call him.　<sub>人称：your → his</sub>
- ✘ Even if I find his passport, I'll call him.　<sub>分句逻辑：If → even if；人称：your → his</sub>
- ✔ If I find your passport, I'll call you.
- ✘ Even if I find your passport, I'll call you.　<sub>分句逻辑：If → even if</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里显式出现了代词（あなた／君），人称不是靠上下文猜的

## 轴：medium｜conj+time（3 题）

**91. 日文**：明日、天気がよければピクニックに行くつもりです。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 即使昨天天气好，那么我们就去野餐。　<sub>分句逻辑：如果 → 即使；时间：明天 → 昨天</sub>
- ✘ 即使明天天气好，那么我们就去野餐。　<sub>分句逻辑：如果 → 即使</sub>
- ✘ 如果昨天天气好，那么我们就去野餐。　<sub>时间：明天 → 昨天</sub>
- ✔ 如果明天天气好，那么我们就去野餐。
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里出现時間名詞「明日」，时间点是显式的

**92. 日文**：夜中に雨が降ったので道がたいへん悪かった。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ The roads were very muddy although it had rained during the morning.　<sub>分句逻辑：since → although；时间：night → morning</sub>
- ✘ The roads were very muddy since it had rained during the morning.　<sub>时间：night → morning</sub>
- ✘ The roads were very muddy although it had rained during the night.　<sub>分句逻辑：since → although</sub>
- ✔ The roads were very muddy since it had rained during the night.
- 依据：日文里有表示原因的「から／ので」，没有逆接的「のに／けど」；日文里出现時間名詞「夜」，时间点是显式的

**93. 日文**：明日天気なら外出します。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✔ I will go out if it is fine tomorrow.
- ✘ I will go out if it is fine today.　<sub>时间：tomorrow → today</sub>
- ✘ I will go out even if it is fine today.　<sub>分句逻辑：if → even if；时间：tomorrow → today</sub>
- ✘ I will go out even if it is fine tomorrow.　<sub>分句逻辑：if → even if</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里出现時間名詞「明日」，时间点是显式的

## 轴：medium｜lexical（3 题）

**94. 日文**：先生はクラスが騒がしいのでしかった。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ The student scolded her class for being noisy.　<sub>具体名词：teacher → student</sub>
- ✔ The teacher scolded her class for being noisy.
- ✘ The doctor scolded her class for being noisy.　<sub>具体名词：teacher → doctor</sub>
- ✘ The police scolded her class for being noisy.　<sub>具体名词：teacher → police</sub>
- 依据：日文里明确说的是「先生」，换成同类的别的东西就与录音不符

**95. 日文**：誰が手紙を書いたの？　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ Who wrote a magazine?　<sub>具体名词：letter → magazine</sub>
- ✘ Who wrote a book?　<sub>具体名词：letter → book</sub>
- ✔ Who wrote a letter?
- ✘ Who wrote a newspaper?　<sub>具体名词：letter → newspaper</sub>
- 依据：日文里明确说的是「手紙」，换成同类的别的东西就与录音不符

**96. 日文**：フランス語ね、書けはしないんだけど、読めるには読める。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ I can't write English, but I can read it.　<sub>具体名词：French → English</sub>
- ✘ I can't write Japanese, but I can read it.　<sub>具体名词：French → Japanese</sub>
- ✘ I can't write Chinese, but I can read it.　<sub>具体名词：French → Chinese</sub>
- ✔ I can't write French, but I can read it.
- 依据：日文里明确说的是「フランス語」，换成同类的别的东西就与录音不符

## 轴：medium｜lexical+number（3 题）

**97. 日文**：学生３枚ください。これが学生証です。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✔ Three students. Here's my student ID.
- ✘ Three students. Here's my teacher ID.　<sub>具体名词：student → teacher</sub>
- ✘ Four students. Here's my teacher ID.　<sub>具体名词：student → teacher；数量：Three → four</sub>
- ✘ Four students. Here's my student ID.　<sub>数量：Three → four</sub>
- 依据：日文里明确说的是「学生」，换成同类的别的东西就与录音不符；日文里出现数词「3」，数量是显式的

**98. 日文**：その学校は１６５０年に設立された。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✔ 这所学校建于1650年。
- ✘ 这所学校建于1651年。　<sub>数量：1650 → 1651</sub>
- ✘ 这所公司建于1651年。　<sub>具体名词：学校 → 公司；数量：1650 → 1651</sub>
- ✘ 这所公司建于1650年。　<sub>具体名词：学校 → 公司</sub>
- 依据：日文里明确说的是「学校」，换成同类的别的东西就与录音不符；日文里出现数词「1650」，数量是显式的

**99. 日文**：学校は８時３０分に始まります。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 学校9点半开始上课。　<sub>数量：8 → 9</sub>
- ✘ 公司8点半开始上课。　<sub>具体名词：学校 → 公司</sub>
- ✘ 公司9点半开始上课。　<sub>具体名词：学校 → 公司；数量：8 → 9</sub>
- ✔ 学校8点半开始上课。
- 依据：日文里明确说的是「学校」，换成同类的别的东西就与录音不符；日文里出现数词「8」，数量是显式的

## 轴：medium｜lexical+person（3 题）

**100. 日文**：日本語は高等学校で教えられていないから、私は一人で勉強する。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ English is not taught in high school, so you study on your own.　<sub>具体名词：Japanese → English；人称：I → you</sub>
- ✔ Japanese is not taught in high school, so I study on my own.
- ✘ Japanese is not taught in high school, so you study on your own.　<sub>人称：I → you</sub>
- ✘ English is not taught in high school, so I study on my own.　<sub>具体名词：Japanese → English</sub>
- 依据：日文里明确说的是「日本語」，换成同类的别的东西就与录音不符；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**101. 日文**：彼の手紙に返事を出さなくちゃいけないかしら。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 我應該回书給你嗎？　<sub>具体名词：信 → 书；人称：他 → 你</sub>
- ✔ 我應該回信給他嗎？
- ✘ 我應該回书給他嗎？　<sub>具体名词：信 → 书</sub>
- ✘ 我應該回信給你嗎？　<sub>人称：他 → 你</sub>
- 依据：日文里明确说的是「手紙」，换成同类的别的东西就与录音不符；日文里显式出现了代词（彼）

**102. 日文**：先日彼女の母が病院で亡くなった。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ The other day my mother passed away in the school.　<sub>具体名词：hospital → school；人称：her → my</sub>
- ✘ The other day her mother passed away in the school.　<sub>具体名词：hospital → school</sub>
- ✔ The other day her mother passed away in the hospital.
- ✘ The other day my mother passed away in the hospital.　<sub>人称：her → my</sub>
- 依据：日文里明确说的是「病院」，换成同类的别的东西就与录音不符；日文里显式出现了代词（彼女），人称不是靠上下文猜的

## 轴：medium｜lexical+quant（3 题）

**103. 日文**：春にはたくさんの美しい花が咲く。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ Many beautiful flowers bloom in summer.　<sub>具体名词：spring → summer</sub>
- ✔ Many beautiful flowers bloom in spring.
- ✘ Few beautiful flowers bloom in spring.　<sub>频度量化：Many → few</sub>
- ✘ Few beautiful flowers bloom in summer.　<sub>具体名词：spring → summer；频度量化：Many → few</sub>
- 依据：日文里明确说的是「春」，换成同类的别的东西就与录音不符；日文里有「たくさん／多く」

**104. 日文**：私は冬によく風邪をひきます。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ I never catch cold in winter.　<sub>频度量化：often → never</sub>
- ✘ I often catch cold in summer.　<sub>具体名词：winter → summer</sub>
- ✘ I never catch cold in summer.　<sub>具体名词：winter → summer；频度量化：often → never</sub>
- ✔ I often catch cold in winter.
- 依据：日文里明确说的是「冬」，换成同类的别的东西就与录音不符；日文里有「よく」

**105. 日文**：母は私達によくアップルパイを焼いてくれる。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✔ 母亲经常为我们做苹果派。
- ✘ 父亲从不为我们做苹果派。　<sub>具体名词：母亲 → 父亲；频度量化：经常 → 从不</sub>
- ✘ 母亲从不为我们做苹果派。　<sub>频度量化：经常 → 从不</sub>
- ✘ 父亲经常为我们做苹果派。　<sub>具体名词：母亲 → 父亲</sub>
- 依据：日文里明确说的是「母」，换成同类的别的东西就与录音不符；日文里有「よく」

## 轴：medium｜lexical+time（3 题）

**106. 日文**：今日は学校の運動会なんだよ。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ Yesterday is our company field day.　<sub>具体名词：school → company；时间：Today → yesterday</sub>
- ✘ Today is our company field day.　<sub>具体名词：school → company</sub>
- ✘ Yesterday is our school field day.　<sub>时间：Today → yesterday</sub>
- ✔ Today is our school field day.
- 依据：日文里明确说的是「学校」，换成同类的别的东西就与录音不符；日文里出现時間名詞「今日」，时间点是显式的

**107. 日文**：先月、僕の叔父の会社が新製品を発売しました。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✔ 舅舅的公司上个月推出了一款新产品。
- ✘ 舅舅的学校上个月推出了一款新产品。　<sub>具体名词：公司 → 学校</sub>
- ✘ 舅舅的公司这个月推出了一款新产品。　<sub>时间：上个月 → 这个月</sub>
- ✘ 舅舅的学校这个月推出了一款新产品。　<sub>具体名词：公司 → 学校；时间：上个月 → 这个月</sub>
- 依据：日文里明确说的是「会社」，换成同类的别的东西就与录音不符；日文里出现時間名詞「先月」，时间点是显式的

**108. 日文**：昨日、ひょんなことで父親の戸籍抄本のコピーを見てしまいました。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ Yesterday I stumbled across a copy of my mother's family register.　<sub>具体名词：father → mother</sub>
- ✔ Yesterday I stumbled across a copy of my father's family register.
- ✘ Today I stumbled across a copy of my mother's family register.　<sub>具体名词：father → mother；时间：Yesterday → today</sub>
- ✘ Today I stumbled across a copy of my father's family register.　<sub>时间：Yesterday → today</sub>
- 依据：日文里明确说的是「父」，换成同类的别的东西就与录音不符；日文里出现時間名詞「昨日」，时间点是显式的

## 轴：medium｜number（3 题）

**109. 日文**：バスは１０分おきに来ます。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ Buses come every eleven minutes.　<sub>数量：ten → eleven</sub>
- ✔ Buses come every ten minutes.
- ✘ Buses come every nine minutes.　<sub>数量：ten → nine</sub>
- ✘ Buses come every twelve minutes.　<sub>数量：ten → twelve</sub>
- 依据：日文里出现数词「10」，数量是显式的

**110. 日文**：父は母より２歳若い。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ 我父亲比我母亲小4岁。　<sub>数量：2 → 4</sub>
- ✔ 我父亲比我母亲小2岁。
- ✘ 我父亲比我母亲小1岁。　<sub>数量：2 → 1</sub>
- ✘ 我父亲比我母亲小3岁。　<sub>数量：2 → 3</sub>
- 依据：日文里出现数词「2」，数量是显式的

**111. 日文**：汽車に揺られつつ、２時間ほどいい気持ちでうとうと眠った。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ I slept drowsily with a good feeling for about 1 hour, while rocked by the train.　<sub>数量：2 → 1</sub>
- ✘ I slept drowsily with a good feeling for about 4 hours, while rocked by the train.　<sub>数量：2 → 4</sub>
- ✘ I slept drowsily with a good feeling for about 3 hours, while rocked by the train.　<sub>数量：2 → 3</sub>
- ✔ I slept drowsily with a good feeling for about 2 hours, while rocked by the train.
- 依据：日文里出现数词「2」，数量是显式的

## 轴：medium｜number+time（3 题）

**112. 日文**：父は朝7時の地下鉄で通勤する。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 爸爸乘中午8点的地铁去上班。　<sub>数量：7 → 8；时间：早上 → 中午</sub>
- ✔ 爸爸乘早上7点的地铁去上班。
- ✘ 爸爸乘早上8点的地铁去上班。　<sub>数量：7 → 8</sub>
- ✘ 爸爸乘中午7点的地铁去上班。　<sub>时间：早上 → 中午</sub>
- 依据：日文里出现数词「7」，数量是显式的；日文里出现時間名詞「朝」，时间点是显式的

**113. 日文**：明日の朝６時に起こして下さい。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✔ 明天早上6点给我打电话。
- ✘ 明天早上7点给我打电话。　<sub>数量：6 → 7</sub>
- ✘ 昨天早上7点给我打电话。　<sub>数量：6 → 7；时间：明天 → 昨天</sub>
- ✘ 昨天早上6点给我打电话。　<sub>时间：明天 → 昨天</sub>
- 依据：日文里出现数词「6」，数量是显式的；日文里出现時間名詞「明日」，时间点是显式的

**114. 日文**：昨日は一日中懸命に働いた。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 今天，我两整天都在工作。　<sub>数量：一 → 两；时间：昨天 → 今天</sub>
- ✘ 昨天，我两整天都在工作。　<sub>数量：一 → 两</sub>
- ✔ 昨天，我一整天都在工作。
- ✘ 今天，我一整天都在工作。　<sub>时间：昨天 → 今天</sub>
- 依据：日文里出现数词「1」，数量是显式的；日文里出现時間名詞「昨日」，时间点是显式的

## 轴：medium｜person（3 题）

**115. 日文**：彼は若かったが、敏腕だった。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✔ Young as he was, he was a man of ability.
- ✘ Young as I was, I was a man of ability.　<sub>人称：he → I</sub>
- ✘ Young as she was, she was a man of ability.　<sub>人称：he → she</sub>
- ✘ Young as you were, you were a man of ability.　<sub>人称：he → you</sub>
- 依据：日文里显式出现了代词（彼），人称不是靠上下文猜的

**116. 日文**：トムの奥さんの名前はメアリーで、彼の息子の名前はホラスです。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ The name of Tom's wife is Mary and my son's is Horace.　<sub>人称：his → my</sub>
- ✔ The name of Tom's wife is Mary and his son's is Horace.
- ✘ The name of Tom's wife is Mary and your son's is Horace.　<sub>人称：his → your</sub>
- ✘ The name of Tom's wife is Mary and her son's is Horace.　<sub>人称：his → her</sub>
- 依据：日文里显式出现了代词（彼），人称不是靠上下文猜的

**117. 日文**：彼女はなぜそんなに心配しているのかしら。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ 不知道我为什么这么担心呢。　<sub>人称：她 → 我</sub>
- ✘ 不知道他为什么这么担心呢。　<sub>人称：她 → 他</sub>
- ✘ 不知道你为什么这么担心呢。　<sub>人称：她 → 你</sub>
- ✔ 不知道她为什么这么担心呢。
- 依据：日文里显式出现了代词（彼女）

## 轴：medium｜person+number（3 题）

**118. 日文**：列車は１０時半に出発するから、１０時にあなたを誘いに行きます。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✔ The train leaves at half past ten, so I'll call for you at ten.
- ✘ The train leaves at half past ten, so I'll call for him at ten.　<sub>人称：you → him</sub>
- ✘ The train leaves at half past eleven, so I'll call for him at ten.　<sub>人称：you → him；数量：ten → eleven</sub>
- ✘ The train leaves at half past eleven, so I'll call for you at ten.　<sub>数量：ten → eleven</sub>
- 依据：日文里显式出现了代词（あなた／君），人称不是靠上下文猜的；日文里出现数词「10」，数量是显式的

**119. 日文**：俺が三歳の時にトムは死んだんだ。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✔ Tom died when I was three.
- ✘ Tom died when you were three.　<sub>人称：I → you</sub>
- ✘ Tom died when I was four.　<sub>数量：three → four</sub>
- ✘ Tom died when you were four.　<sub>人称：I → you；数量：three → four</sub>
- 依据：日文里显式出现了代词（私／僕），人称不是靠上下文猜的；日文里出现数词「3」，数量是显式的

**120. 日文**：私がここに引っ越してきて３年になる。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ It's been three years since you moved here.　<sub>人称：I → you</sub>
- ✘ It's been four years since you moved here.　<sub>人称：I → you；数量：three → four</sub>
- ✔ It's been three years since I moved here.
- ✘ It's been four years since I moved here.　<sub>数量：three → four</sub>
- 依据：日文里显式出现了代词（私／僕），人称不是靠上下文猜的；日文里出现数词「3」，数量是显式的

## 轴：medium｜quant+number（3 题）

**121. 日文**：そのパーティーに姿を見せたのは１０人だけだった。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ Also eleven people showed up for the party.　<sub>频度量化：Only → also；数量：ten → eleven</sub>
- ✘ Only eleven people showed up for the party.　<sub>数量：ten → eleven</sub>
- ✘ Also ten people showed up for the party.　<sub>频度量化：Only → also</sub>
- ✔ Only ten people showed up for the party.
- 依据：日文里有「だけ／しか」；日文里出现数词「10」，数量是显式的

**122. 日文**：バスタオルが１枚しかありません。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 只有两條浴巾。　<sub>数量：一 → 两</sub>
- ✘ 也有一條浴巾。　<sub>频度量化：只有 → 也有</sub>
- ✘ 也有两條浴巾。　<sub>频度量化：只有 → 也有；数量：一 → 两</sub>
- ✔ 只有一條浴巾。
- 依据：日文里有「だけ／しか」；日文里出现数词「1」，数量是显式的

**123. 日文**：私は口だけが一つありますが、耳が２つあります。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ I also have one mouth, but I have two ears.　<sub>频度量化：only → also</sub>
- ✘ I also have one mouth, but I have three ears.　<sub>频度量化：only → also；数量：two → three</sub>
- ✔ I only have one mouth, but I have two ears.
- ✘ I only have one mouth, but I have three ears.　<sub>数量：two → three</sub>
- 依据：日文里有「だけ／しか」；日文里出现数词「2」，数量是显式的

## 轴：medium｜quant+person（3 题）

**124. 日文**：学生のころ私はよく彼女に手紙を書いた。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ I never wrote to her when I was a student.　<sub>频度量化：often → never</sub>
- ✔ I often wrote to her when I was a student.
- ✘ I often wrote to you when I was a student.　<sub>人称：her → you</sub>
- ✘ I never wrote to you when I was a student.　<sub>频度量化：often → never；人称：her → you</sub>
- 依据：日文里有「よく」；日文里显式出现了代词（彼女），人称不是靠上下文猜的

**125. 日文**：それはあなたの気のせいだけです。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 那只是我的想象。　<sub>人称：你 → 我</sub>
- ✔ 那只是你的想象。
- ✘ 那也有我的想象。　<sub>频度量化：只是 → 也有；人称：你 → 我</sub>
- ✘ 那也有你的想象。　<sub>频度量化：只是 → 也有</sub>
- 依据：日文里有「だけ／しか」；日文里显式出现了代词（あなた／君）

**126. 日文**：君に会うのはいつも楽しい。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ It's never delightful to see you.　<sub>频度量化：always → never</sub>
- ✘ It's never delightful to see me.　<sub>频度量化：always → never；人称：you → me</sub>
- ✘ It's always delightful to see me.　<sub>人称：you → me</sub>
- ✔ It's always delightful to see you.
- 依据：日文里有「いつも／ずっと」；日文里显式出现了代词（あなた／君），人称不是靠上下文猜的

## 轴：medium｜time（3 题）

**127. 日文**：昨日学校を休んだ理由をいいなさい。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✔ Tell me the reason for your absence from school yesterday.
- ✘ Tell me the reason for your absence from school the day after tomorrow.　<sub>时间：yesterday → the day after tomorrow</sub>
- ✘ Tell me the reason for your absence from school today.　<sub>时间：yesterday → today</sub>
- ✘ Tell me the reason for your absence from school tomorrow.　<sub>时间：yesterday → tomorrow</sub>
- 依据：日文里出现時間名詞「昨日」，时间点是显式的

**128. 日文**：今日のビールを取るか、明日の学位を取るか。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ A beer yesterday or a degree tomorrow?　<sub>时间：today → yesterday</sub>
- ✘ A beer the day before yesterday or a degree tomorrow?　<sub>时间：today → the day before yesterday</sub>
- ✘ A beer the day after tomorrow or a degree tomorrow?　<sub>时间：today → the day after tomorrow</sub>
- ✔ A beer today or a degree tomorrow?
- 依据：日文里出现時間名詞「今日」，时间点是显式的

**129. 日文**：昨日は小雨が降った。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ 今天下小雨。　<sub>时间：昨天 → 今天</sub>
- ✘ 明天下小雨。　<sub>时间：昨天 → 明天</sub>
- ✘ 后天下小雨。　<sub>时间：昨天 → 后天</sub>
- ✔ 昨天下小雨。
- 依据：日文里出现時間名詞「昨日」，时间点是显式的

## 轴：easy｜polarity+modal（2 题）

**130. 日文**：ケイさんという方がお目にかかりたいそうです。　`matrix_2x2`　难度 `easy`（听辨区：tail）

- ✘ 没有位凱先生必须見你。　<sub>肯否：有 → 没有；情态：想 → 必须</sub>
- ✘ 有位凱先生必须見你。　<sub>情态：想 → 必须</sub>
- ✔ 有位凱先生想見你。
- ✘ 没有位凱先生想見你。　<sub>肯否：有 → 没有</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事；日文里有愿望形「〜たい」

**131. 日文**：こんなに悪い天候の中で登山するべきではない。　`matrix_2x2`　难度 `easy`（听辨区：tail）

- ✔ You should not climb the mountain in such bad weather.
- ✘ You should climb the mountain in such bad weather.　<sub>肯否：not 被去掉</sub>
- ✘ You must climb the mountain in such bad weather.　<sub>肯否：not 被去掉；情态：should → must</sub>
- ✘ You must not climb the mountain in such bad weather.　<sub>情态：should → must</sub>
- 依据：日文句尾谓语带否定形态素（ない／ません／ぬ），录音说的是「没有／不」；日文里有建议表达「〜ほうがいい／〜べき」

## 轴：hard｜conj+tense（2 题）

**132. 日文**：公衆の面前に姿を見せなければならないのが厭だった。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ He was annoyed at having to show up after the public.　<sub>分句逻辑：before → after</sub>
- ✘ He is annoyed at having to show up after the public.　<sub>分句逻辑：before → after；时制：was → is</sub>
- ✔ He was annoyed at having to show up before the public.
- ✘ He is annoyed at having to show up before the public.　<sub>时制：was → is</sub>
- 依据：日文里有「〜前に」，先后顺序是显式的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

**133. 日文**：それ以前に彼女と会ったことはなかった。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ I had never seen her after that time.　<sub>分句逻辑：before → after</sub>
- ✘ I will have never seen her after that time.　<sub>分句逻辑：before → after；时制：had → will have</sub>
- ✘ I will have never seen her before that time.　<sub>时制：had → will have</sub>
- ✔ I had never seen her before that time.
- 依据：日文里有「〜前に」，先后顺序是显式的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

## 轴：hard｜modal+time（2 题）

**134. 日文**：来月は、損失を取り返さねばならない。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ The loss must be made up for next month.
- ✘ The loss must be made up for last month.　<sub>时间：next month → last month</sub>
- ✘ The loss may be made up for last month.　<sub>情态：must → may；时间：next month → last month</sub>
- ✘ The loss may be made up for next month.　<sub>情态：must → may</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里出现時間名詞「来月」，时间点是显式的

**135. 日文**：だいたい何でこんな真夜中にジュース買う為にパシらされなきゃなんないんだか・・・。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ Anyhow, just why is it that I may be sent out in the middle of the night to buy a canned drink?　<sub>情态：have to → may</sub>
- ✘ Anyhow, just why is it that I have to be sent out in the middle of the morning to buy a canned drink?　<sub>时间：night → morning</sub>
- ✘ Anyhow, just why is it that I may be sent out in the middle of the morning to buy a canned drink?　<sub>情态：have to → may；时间：night → morning</sub>
- ✔ Anyhow, just why is it that I have to be sent out in the middle of the night to buy a canned drink?
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里出现時間名詞「夜」，时间点是显式的

## 轴：hard｜role+tense（2 题）

**136. 日文**：彼女は彼に食べ過ぎないように忠告した。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✘ He will advise her not to eat too much.　<sub>施受：She ↔ him 施受互换；时制：advised → will advise</sub>
- ✔ She advised him not to eat too much.
- ✘ He advised her not to eat too much.　<sub>施受：She ↔ him 施受互换</sub>
- ✘ She will advise him not to eat too much.　<sub>时制：advised → will advise</sub>
- 依据：日文里表示对象的代词带「を/に」格助词，施受方向是显式的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

**137. 日文**：私は彼に運転しないように助言した。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ I advised him not to drive.
- ✘ He advised me not to drive.　<sub>施受：I ↔ him 施受互换</sub>
- ✘ I will advise him not to drive.　<sub>时制：advised → will advise</sub>
- ✘ He will advise me not to drive.　<sub>施受：I ↔ him 施受互换；时制：advised → will advise</sub>
- 依据：日文里表示对象的代词带「を/に」格助词，施受方向是显式的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

## 轴：medium｜quant+time（2 题）

**138. 日文**：「昨日の今日だし・・・その・・・性器が痛かったりは？」「まだ、少しヒリヒリしますけど」　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ "It's right after yesterday so... that is... do your genitals hurt or...?" "It no longer smarts a little but..."　<sub>频度量化：still → no longer</sub>
- ✘ "It's right after tomorrow so... that is... do your genitals hurt or...?" "It still smarts a little but..."　<sub>时间：yesterday → tomorrow</sub>
- ✔ "It's right after yesterday so ... that is ... do your genitals hurt or ...?" "It still smarts a little but..."
- ✘ "It's right after tomorrow so... that is... do your genitals hurt or...?" "It no longer smarts a little but..."　<sub>频度量化：still → no longer；时间：yesterday → tomorrow</sub>
- 依据：日文里有「まだ」；日文里出现時間名詞「昨日」，时间点是显式的

**139. 日文**：今日しなければならない宿題がたくさんある。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ I have a lot of assignments to do yesterday.　<sub>时间：today → yesterday</sub>
- ✔ I have a lot of assignments to do today.
- ✘ I have a little assignments to do today.　<sub>频度量化：a lot of → a little</sub>
- ✘ I have a little assignments to do yesterday.　<sub>频度量化：a lot of → a little；时间：today → yesterday</sub>
- 依据：日文里有「たくさん／多く」；日文里出现時間名詞「今日」，时间点是显式的

## 轴：hard｜person+tense（1 题）

**140. 日文**：彼はわざとそうしたのではないかという考えが、ふと私の頭をよぎった。　`matrix_2x2`　难度 `hard`（听辨区：mid+tail）

- ✔ It occurred to me that he had done it on purpose.
- ✘ It occurred to me that he will have done it on purpose.　<sub>时制：had → will have</sub>
- ✘ It occurred to you that he will have done it on purpose.　<sub>人称：me → you；时制：had → will have</sub>
- ✘ It occurred to you that he had done it on purpose.　<sub>人称：me → you</sub>
- 依据：日文里显式出现了代词（私／僕），人称不是靠上下文猜的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

## 轴：hard｜place+person（1 题）

**141. 日文**：彼は机を右に移動させた。　`matrix_2x2`　难度 `hard`（听辨区：head+mid）

- ✔ 他往右边移了书桌。
- ✘ 我往左边移了书桌。　<sub>方位：右边 → 左边；人称：他 → 我</sub>
- ✘ 他往左边移了书桌。　<sub>方位：右边 → 左边</sub>
- ✘ 我往右边移了书桌。　<sub>人称：他 → 我</sub>
- 依据：日文里出现方位名词「右」，位置关系是显式的；日文里显式出现了代词（彼）

## 轴：medium｜conj+number（1 题）

**142. 日文**：出発２０分前になったら、搭乗案内のアナウンスがかかるって。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✔ They said they'd make the boarding announcement 20 minutes before takeoff.
- ✘ They said they'd make the boarding announcement 20 minutes after takeoff.　<sub>分句逻辑：before → after</sub>
- ✘ They said they'd make the boarding announcement 30 minutes after takeoff.　<sub>分句逻辑：before → after；数量：20 → 30</sub>
- ✘ They said they'd make the boarding announcement 30 minutes before takeoff.　<sub>数量：20 → 30</sub>
- 依据：日文里有「〜前に」，先后顺序是显式的；日文里出现数词「20」，数量是显式的

## 轴：medium｜direction+conj（1 题）

**143. 日文**：新幹線なら、名古屋から東京もそんなに遠く感じないよ。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ Even if you travel by Shinkansen, it doesn't seem far from Nagoya to Tokyo.　<sub>分句逻辑：If → even if</sub>
- ✘ Even if you travel by Shinkansen, it doesn't seem far from Tokyo to Nagoya.　<sub>起讫点：from Nagoya to Tokyo → from Tokyo to Nagoya；分句逻辑：If → even if</sub>
- ✔ If you travel by Shinkansen, it doesn't seem far from Nagoya to Tokyo.
- ✘ If you travel by Shinkansen, it doesn't seem far from Tokyo to Nagoya.　<sub>起讫点：from Nagoya to Tokyo → from Tokyo to Nagoya</sub>
- 依据：日文用「〜から」「〜へ／まで」显式标出了起点和终点；日文里有条件形「〜たら／〜ば／〜なら」

## 轴：medium｜person+time（1 题）

**144. 日文**：明日彼を訪問します。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 明天我將拜訪你。　<sub>人称：他 → 你</sub>
- ✘ 今天我將拜訪他。　<sub>时间：明天 → 今天</sub>
- ✔ 明天我將拜訪他。
- ✘ 今天我將拜訪你。　<sub>人称：他 → 你；时间：明天 → 今天</sub>
- 依据：日文里显式出现了代词（彼）；日文里出现時間名詞「明日」，时间点是显式的

## 轴：medium｜quant（1 题）

**145. 日文**：それは決して消えることはない。　`four_way_slot`　难度 `medium`（听辨区：mid）

- ✘ That will often disappear.　<sub>频度量化：never → often</sub>
- ✘ That will sometimes disappear.　<sub>频度量化：never → sometimes</sub>
- ✘ That will always disappear.　<sub>频度量化：never → always</sub>
- ✔ That will never disappear.
- 依据：日文里有「全然／決して」＋否定

## 轴：medium｜role+quant（1 题）

**146. 日文**：彼等は私にたくさんの美しい写真を見せてくれました。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 他們給我看了很少漂亮的照片。　<sub>频度量化：很多 → 很少</sub>
- ✘ 我給他們看了很多漂亮的照片。　<sub>施受：他們 ↔ 我 互换</sub>
- ✘ 我給他們看了很少漂亮的照片。　<sub>施受：他們 ↔ 我 互换；频度量化：很多 → 很少</sub>
- ✔ 他們給我看了很多漂亮的照片。
- 依据：日文里表示对象的代词带「を／に」格助词，谁对谁做是显式的；日文里有「たくさん／多く」

## 轴：medium｜role+time（1 题）

**147. 日文**：今日彼に電話をするのを忘れた。　`matrix_2x2`　难度 `medium`（听辨区：mid）

- ✘ 他今天忘记给我打电话了。　<sub>施受：我 ↔ 他 互换</sub>
- ✘ 他昨天忘记给我打电话了。　<sub>施受：我 ↔ 他 互换；时间：今天 → 昨天</sub>
- ✘ 我昨天忘记给他打电话了。　<sub>时间：今天 → 昨天</sub>
- ✔ 我今天忘记给他打电话了。
- 依据：日文里表示对象的代词带「を／に」格助词，谁对谁做是显式的；日文里出现時間名詞「今日」，时间点是显式的
